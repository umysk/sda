# Copyright (c) 2026 U
"""ワーカープロセスのエントリーポイント。spawn / forkserver で起動されるサブプロセス内で実行される。"""

import contextlib
import logging
import logging.handlers
import sys
import traceback
from collections.abc import Callable
from multiprocessing.queues import Queue
from typing import Any


def run(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    error_queue: Queue[dict[str, str]],
    log_queue: Queue[logging.LogRecord],
) -> None:
    """ワーカープロセスのメイン関数。

    ルートロガーに QueueHandler を設定し、すべてのログレコードを
    メインプロセスのリスナーへ転送する。
    関数が例外で終了した場合は error_queue にエラー情報を積んで sys.exit(1) する。
    os._exit() やシグナルによる強制終了はこの関数では捕捉できないが、
    モニタースレッドが exitcode で検知する。

    Parameters
    ----------
    func : Callable[..., Any]
        実行するユーザー関数。pickle 可能である必要がある。
    args : tuple[Any, ...]
        func に渡す位置引数。
    kwargs : dict[str, Any]
        func に渡すキーワード引数。
    error_queue : Queue[dict[str, str]]
        例外情報を転送するキュー。失敗時のみ書き込む。
    log_queue : Queue[logging.LogRecord]
        LogRecord を転送するキュー。QueueHandler が書き込む。

    """
    # ルートロガーのハンドラーをすべて QueueHandler に置き換える
    root: logging.Logger = logging.getLogger()
    root.handlers.clear()
    root.addHandler(logging.handlers.QueueHandler(log_queue))
    root.setLevel(logging.DEBUG)

    try:
        func(*args, **kwargs)
    except Exception as exc_value:  # noqa: BLE001 - ユーザー関数の任意の例外を捕捉する
        tb: str = traceback.format_exc()
        # os._exit() ではここに来ないが、通常の例外はキューに積んで終了する
        with contextlib.suppress(Exception):
            error_queue.put_nowait(
                {
                    "type": type(exc_value).__name__,
                    "message": str(exc_value),
                    "traceback": tb,
                }
            )
        sys.exit(1)
