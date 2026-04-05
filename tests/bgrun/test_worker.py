# Copyright (c) 2026 U
"""_worker.run() の単体テスト。

run() を直接呼び出すことで、サブプロセスを起動せずにユニットテストを行う。
関数はピクル不要なため、クロージャも使用可能。
"""

import logging
import logging.handlers
import multiprocessing
from collections.abc import Generator
from multiprocessing.context import ForkServerContext
from typing import Any

import pytest

from sda.bgrun._worker import run as worker_run

# Queue 生成に使用するコンテキスト
_CTX: ForkServerContext = multiprocessing.get_context("forkserver")


# ---- フィクスチャ ----
@pytest.fixture(autouse=True)
def _restore_root_logger() -> Generator[None]:
    """run() が変更するルートロガーをテスト後に復元する。"""
    root: logging.Logger = logging.getLogger()
    original_handlers: list[logging.Handler] = root.handlers[:]
    original_level: int = root.level
    yield
    root.handlers = original_handlers
    root.setLevel(original_level)


# ---- 正常系 ----
class TestWorkerRunSuccess:
    """正常終了シナリオのテスト。"""

    @staticmethod
    def test_run_calls_func() -> None:
        """ユーザー関数が呼ばれる。"""
        called: list[bool] = []

        def _func() -> None:
            called.append(True)

        worker_run(_func, (), {}, _CTX.Queue(), _CTX.Queue())
        assert called == [True]

    @staticmethod
    def test_run_passes_args() -> None:
        """位置引数が func に渡される。"""
        received: list[Any] = []

        def _func(a: int, b: int) -> None:
            received.extend([a, b])

        worker_run(_func, (1, 2), {}, _CTX.Queue(), _CTX.Queue())
        assert received == [1, 2]

    @staticmethod
    def test_run_passes_kwargs() -> None:
        """キーワード引数が func に渡される。"""
        received: dict[str, Any] = {}

        def _func(*, key: str = "") -> None:
            received["key"] = key

        worker_run(_func, (), {"key": "テスト値"}, _CTX.Queue(), _CTX.Queue())
        assert received == {"key": "テスト値"}

    @staticmethod
    def test_run_error_queue_empty_on_success() -> None:
        """成功時は error_queue が空のまま。"""
        error_queue = _CTX.Queue()

        def _noop() -> None:
            pass

        worker_run(_noop, (), {}, error_queue, _CTX.Queue())
        assert error_queue.empty()


# ---- 例外系 ----
class TestWorkerRunException:
    """例外終了シナリオのテスト。"""

    @staticmethod
    def test_run_raises_system_exit_on_exception() -> None:
        """例外発生時に SystemExit(1) が送出される。"""

        def _raise() -> None:
            msg = "テスト用エラー"
            raise RuntimeError(msg)

        with pytest.raises(SystemExit) as exc_info:
            worker_run(_raise, (), {}, _CTX.Queue(), _CTX.Queue())
        assert exc_info.value.code == 1

    @staticmethod
    def test_run_error_queue_has_exception_type() -> None:
        """error_queue に例外の型名が入る。"""
        error_queue = _CTX.Queue()

        def _raise() -> None:
            msg = "テスト用エラー"
            raise ValueError(msg)

        with pytest.raises(SystemExit):
            worker_run(_raise, (), {}, error_queue, _CTX.Queue())
        error_info = error_queue.get(timeout=1.0)
        assert error_info["type"] == "ValueError"

    @staticmethod
    def test_run_error_queue_has_message() -> None:
        """error_queue に例外メッセージが入る。"""
        error_queue = _CTX.Queue()

        def _raise() -> None:
            msg = "エラーメッセージ"
            raise RuntimeError(msg)

        with pytest.raises(SystemExit):
            worker_run(_raise, (), {}, error_queue, _CTX.Queue())
        error_info = error_queue.get(timeout=1.0)
        assert "エラーメッセージ" in error_info["message"]

    @staticmethod
    def test_run_error_queue_has_traceback() -> None:
        """error_queue にトレースバック文字列が入る。"""
        error_queue = _CTX.Queue()

        def _raise() -> None:
            msg = "テスト用エラー"
            raise ValueError(msg)

        with pytest.raises(SystemExit):
            worker_run(_raise, (), {}, error_queue, _CTX.Queue())
        error_info = error_queue.get(timeout=1.0)
        assert "ValueError" in error_info["traceback"]


# ---- ログ転送 ----
class TestWorkerLogForwarding:
    """ログ転送のテスト。"""

    @staticmethod
    def test_run_sets_queue_handler_on_root_logger() -> None:
        """run() がルートロガーに QueueHandler を設定する。"""

        def _noop() -> None:
            pass

        worker_run(_noop, (), {}, _CTX.Queue(), _CTX.Queue())
        root = logging.getLogger()
        assert any(isinstance(h, logging.handlers.QueueHandler) for h in root.handlers)

    @staticmethod
    def test_run_log_record_goes_to_log_queue() -> None:
        """ユーザー関数内のログが log_queue に届く。"""
        log_queue = _CTX.Queue()

        def _emit_log() -> None:
            logging.getLogger("test.worker").info("ログメッセージ")

        worker_run(_emit_log, (), {}, _CTX.Queue(), log_queue)
        record: logging.LogRecord = log_queue.get(timeout=1.0)
        assert "ログメッセージ" in record.getMessage()
