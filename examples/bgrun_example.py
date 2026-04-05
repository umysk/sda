# Copyright (c) 2026 U
"""bgrun の動作確認サンプル。"""

import contextlib
import logging
import os
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path

import sda

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger: logging.Logger = logging.getLogger("example")


# ---- サンプル関数群 ----
def normal_task(duration: float) -> None:
    """正常終了するタスク。"""
    log: logging.Logger = logging.getLogger("example.normal_task")
    log.info("%s秒間のタスクを開始します", duration)
    time.sleep(duration)
    log.info("タスク完了")


def error_task() -> None:
    """例外で失敗するタスク。

    Raises
    ------
    ValueError
        意図的なエラーを発生させる。

    """
    log: logging.Logger = logging.getLogger("example.error_task")
    log.info("エラータスクを開始します")
    time.sleep(0.5)
    msg = "意図的なエラー"
    raise ValueError(msg)


def exit_task() -> None:
    """os._exit(1) で強制終了するタスク。"""
    log: logging.Logger = logging.getLogger("example.exit_task")
    log.info("os._exit(1) で終了します")
    time.sleep(0.3)
    os._exit(1)


def oom_task(succeed_after: int = 0) -> None:
    """指定回数だけ SIGKILL で自爆し、その後正常終了するタスク。

    Parameters
    ----------
    succeed_after : int
        この回数だけ SIGKILL で終了した後、正常終了する。
        0 の場合は常に SIGKILL で終了する。

    """
    log: logging.Logger = logging.getLogger("example.oom_task")

    # 試行カウントをファイルで共有 (spawn/forkserver はメモリを共有しない)
    counter_path = Path(f"/tmp/oom_example_counter_{os.getppid()}")  # noqa: S108
    count: int = 0
    with contextlib.suppress(FileNotFoundError, ValueError):
        count = int(counter_path.read_text(encoding="utf-8").strip())

    log.info("OOM シミュレーション開始 (試行回数: %s, succeed_after: %s)", count + 1, succeed_after)
    time.sleep(0.3)

    if succeed_after == 0 or count < succeed_after:
        counter_path.write_text(str(count + 1), encoding="utf-8")
        log.warning("OOM killer をシミュレート: SIGKILL を自プロセスに送信します")
        os.kill(os.getpid(), signal.SIGKILL)
    else:
        with contextlib.suppress(FileNotFoundError):
            counter_path.unlink()
        log.info("正常終了します")


# ---- 各シナリオの実行 ----
def run_normal() -> None:
    """シナリオ1: 正常終了を実行する。"""
    logger.info("=== シナリオ1: 正常終了 ===")
    task = sda.BackgroundTask(
        func=normal_task,
        args=(2.0,),
        logger=logger,
    )
    task.run()
    logger.info("ステータス: %s", task.status)


def run_error_with_retry() -> None:
    """シナリオ2: エラー終了 (max_retries=2, retry_on_exception=True) を実行する。"""
    logger.info("=== シナリオ2: エラー終了 (max_retries=2, retry_on_exception=True) ===")
    task = sda.BackgroundTask(
        func=error_task,
        max_retries=2,
        retry_delay=1.0,
        retry_on_exception=True,
        logger=logger,
    )
    try:
        task.run()
    except sda.MaxRetriesExceededError:
        logger.exception("最大リトライ到達")
    logger.info("ステータス: %s", task.status)


def run_os_exit_with_retry() -> None:
    """シナリオ3: os._exit(1) (max_retries=1, retry_on_os_exit=True) を実行する。"""
    logger.info("=== シナリオ3: os._exit(1) (max_retries=1, retry_on_os_exit=True) ===")
    task = sda.BackgroundTask(
        func=exit_task,
        max_retries=1,
        retry_delay=1.0,
        retry_on_os_exit=True,
        logger=logger,
    )
    try:
        task.run()
    except sda.MaxRetriesExceededError:
        logger.exception("最大リトライ到達")
    logger.info("ステータス: %s", task.status)


def _cleanup_oom_counter() -> None:
    Path(f"/tmp/oom_example_counter_{os.getpid()}").unlink(missing_ok=True)  # noqa: S108


def run_oom_retry() -> None:
    """シナリオ4: OOM killer をシミュレートし、デフォルト設定でリトライして回復する。

    retry_signals のデフォルト値は {-9} (SIGKILL) なので、
    max_retries=3 を指定するだけで OOM リトライが有効になる。
    2 回 SIGKILL で終了した後、3 回目で正常終了する。
    """
    _cleanup_oom_counter()
    logger.info("=== シナリオ4: OOM killer リトライ (デフォルト設定, succeed_after=2) ===")
    task = sda.BackgroundTask(
        func=oom_task,
        kwargs={"succeed_after": 2},
        max_retries=3,
        retry_delay=1.0,
        logger=logger,
        # retry_signals のデフォルトは {-9} (SIGKILL = OOM killer)
    )
    task.run()
    logger.info("ステータス: %s", task.status)


def run_oom_no_retry() -> None:
    """シナリオ5: OOM killer をシミュレートし、retry_signals=False でリトライしない。"""
    _cleanup_oom_counter()
    logger.info("=== シナリオ5: OOM killer リトライなし (retry_signals=False) ===")
    task = sda.BackgroundTask(
        func=oom_task,
        kwargs={"succeed_after": 0},
        max_retries=3,
        retry_delay=1.0,
        retry_signals=False,
        logger=logger,
    )
    try:
        task.run()
    except sda.TaskError:
        logger.exception("タスク失敗")
    logger.info("ステータス: %s", task.status)


def run_oom_exceed() -> None:
    """シナリオ6: OOM killer をシミュレートし、最大リトライ回数を超過する。

    succeed_after=99 なので常に SIGKILL で終了し、
    max_retries=2 を使い切って MaxRetriesExceededError が発生する。
    """
    _cleanup_oom_counter()
    logger.info("=== シナリオ6: OOM killer リトライ上限超過 (max_retries=2, 常に SIGKILL) ===")
    task = sda.BackgroundTask(
        func=oom_task,
        kwargs={"succeed_after": 99},
        max_retries=2,
        retry_delay=1.0,
        logger=logger,
    )
    try:
        task.run()
    except sda.MaxRetriesExceededError:
        logger.exception("最大リトライ到達")
    logger.info("ステータス: %s", task.status)


def run_cancel() -> None:
    """シナリオ7: キャンセルを実行する。"""
    logger.info("=== シナリオ7: キャンセル ===")
    task = sda.BackgroundTask(
        func=normal_task,
        args=(30.0,),
        logger=logger,
    )
    task.start()
    time.sleep(1.5)
    task.cancel()
    task.wait()
    logger.info("ステータス: %s", task.status)


if __name__ == "__main__":
    scenario: str = sys.argv[1] if len(sys.argv) > 1 else "all"

    scenarios: dict[str, Callable[[], None]] = {
        "normal": run_normal,
        "error": run_error_with_retry,
        "exit": run_os_exit_with_retry,
        "oom_retry": run_oom_retry,
        "oom_no_retry": run_oom_no_retry,
        "oom_exceed": run_oom_exceed,
        "cancel": run_cancel,
    }

    if scenario == "all":
        for fn in scenarios.values():
            fn()
            print()
    elif scenario in scenarios:
        scenarios[scenario]()
    else:
        print(f"使用法: python example.py [{'|'.join(scenarios)}|all]")
