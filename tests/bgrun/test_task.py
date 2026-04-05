# Copyright (c) 2026 U
"""BackgroundTask の動作テスト。

各テストは start_method='forkserver' を使用する。
forkserver は初回起動時にサーバープロセスを1つ立ち上げ、
以降はそこから fork するため spawn より高速。
"""

import logging
import os
import platform
import signal
import time

import pytest

from sda.bgrun import BackgroundTask, MaxRetriesExceededError, TaskError, TaskStatus
from sda.bgrun._task import _describe_exitcode, _resolve_start_method


# ---- テスト用関数 (モジュールレベルに定義: pickle 必須) ----
def _succeed(duration: float = 0.1) -> None:
    time.sleep(duration)


def _require_kwarg(key: str = "") -> None:
    if key != "テスト値":
        msg: str = f"kwargs が渡されていません: {key!r}"
        raise ValueError(msg)


def _raise_value_error() -> None:
    msg = "テスト用エラー"
    raise ValueError(msg)


def _os_exit() -> None:
    os._exit(1)


def _send_sigterm() -> None:
    os.kill(os.getpid(), signal.SIGTERM)


def _send_sigkill() -> None:
    os.kill(os.getpid(), signal.SIGKILL)


def _log_and_succeed(message: str) -> None:
    logging.getLogger("worker").info(message)


# ---- 正常系 ----
class TestNormalCompletion:
    """正常終了シナリオのテスト。"""

    @staticmethod
    def test_status_becomes_completed() -> None:
        """正常終了後のステータスが COMPLETED になる。"""
        task = BackgroundTask(func=_succeed, start_method="forkserver")
        task.run()
        assert task.status == TaskStatus.COMPLETED

    @staticmethod
    def test_run_returns_without_exception() -> None:
        """run() が例外なしで返る。"""
        task = BackgroundTask(func=_succeed, start_method="forkserver")
        task.run()

    @staticmethod
    def test_start_then_wait() -> None:
        """start() + wait() の組み合わせで正常終了する。"""
        task = BackgroundTask(func=_succeed, start_method="forkserver")
        task.start()
        task.wait()
        assert task.status == TaskStatus.COMPLETED

    @staticmethod
    def test_worker_logs_forwarded(caplog: pytest.LogCaptureFixture) -> None:
        """ワーカーのログがメインプロセスに転送される。"""
        with caplog.at_level(logging.INFO, logger="worker"):
            task = BackgroundTask(
                func=_log_and_succeed,
                args=("ワーカーからのログ",),
                start_method="forkserver",
            )
            task.run()
        assert any("ワーカーからのログ" in r.message for r in caplog.records)

    @staticmethod
    def test_initial_status_is_pending() -> None:
        """インスタンス生成直後のステータスが PENDING になる。"""
        task = BackgroundTask(func=_succeed)
        assert task.status == TaskStatus.PENDING

    @staticmethod
    def test_kwargs_passed_to_func() -> None:
        """指定した kwargs が正しくワーカーに渡される。"""
        task = BackgroundTask(
            func=_require_kwarg,
            kwargs={"key": "テスト値"},
            start_method="forkserver",
        )
        task.run()

    @staticmethod
    def test_spawn_start_method_works() -> None:
        """start_method='spawn' で正常終了する。"""
        task = BackgroundTask(func=_succeed, start_method="spawn")
        task.run()
        assert task.status == TaskStatus.COMPLETED

    @staticmethod
    def test_custom_logger_receives_log(caplog: pytest.LogCaptureFixture) -> None:
        """カスタムロガーにタスクのログが出力される。"""
        custom_logger: logging.Logger = logging.getLogger("test.custom")
        task = BackgroundTask(func=_succeed, start_method="forkserver", logger=custom_logger)
        with caplog.at_level(logging.INFO, logger="test.custom"):
            task.run()
        assert any(r.name == "test.custom" for r in caplog.records)


# ---- エラー系 (リトライなし) ----
class TestErrorNoRetry:
    """リトライなしのエラーシナリオのテスト。"""

    @staticmethod
    def test_raises_task_error() -> None:
        """例外終了時に TaskError が送出される。"""
        task = BackgroundTask(func=_raise_value_error, start_method="forkserver")
        with pytest.raises(TaskError):
            task.run()

    @staticmethod
    def test_status_becomes_error() -> None:
        """例外終了後のステータスが ERROR になる。"""
        task = BackgroundTask(func=_raise_value_error, start_method="forkserver")
        with pytest.raises(TaskError):
            task.run()
        assert task.status == TaskStatus.ERROR

    @staticmethod
    def test_task_error_not_max_retries() -> None:
        """リトライなしの場合は MaxRetriesExceededError でなく TaskError が送出される。"""
        task = BackgroundTask(func=_raise_value_error, start_method="forkserver")
        with pytest.raises(TaskError) as exc_info:
            task.run()
        assert not isinstance(exc_info.value, MaxRetriesExceededError)

    @staticmethod
    def test_original_traceback_included() -> None:
        """TaskError にワーカーのトレースバックが含まれる。"""
        task = BackgroundTask(func=_raise_value_error, start_method="forkserver")
        with pytest.raises(TaskError) as exc_info:
            task.run()
        assert "ValueError" in exc_info.value.original_traceback


# ---- エラー系 (リトライあり) ----
class TestErrorWithRetry:
    """リトライありのエラーシナリオのテスト。"""

    @staticmethod
    def test_raises_max_retries_exceeded() -> None:
        """最大リトライ到達後に MaxRetriesExceededError が送出される。"""
        task = BackgroundTask(
            func=_raise_value_error,
            max_retries=2,
            retry_delay=0.1,
            start_method="forkserver",
            retry_on_exception=True,
        )
        with pytest.raises(MaxRetriesExceededError):
            task.run()

    @staticmethod
    def test_max_retries_exceeded_is_task_error_subclass() -> None:
        """MaxRetriesExceededError は TaskError のサブクラス。"""
        task = BackgroundTask(
            func=_raise_value_error,
            max_retries=1,
            retry_delay=0.1,
            start_method="forkserver",
            retry_on_exception=True,
        )
        with pytest.raises(TaskError):
            task.run()

    @staticmethod
    def test_status_becomes_error_after_retries() -> None:
        """最大リトライ到達後のステータスが ERROR になる。"""
        task = BackgroundTask(
            func=_raise_value_error,
            max_retries=1,
            retry_delay=0.1,
            start_method="forkserver",
            retry_on_exception=True,
        )
        with pytest.raises(MaxRetriesExceededError):
            task.run()
        assert task.status == TaskStatus.ERROR

    @staticmethod
    @pytest.mark.parametrize(
        ("retry_on_exception", "expect_max_retries_exceeded"),
        [
            pytest.param(True, True, id="retried"),
            pytest.param(False, False, id="not_retried"),
        ],
    )
    def test_exception_retry_behavior(retry_on_exception: bool, expect_max_retries_exceeded: bool) -> None:
        """retry_on_exception の設定によりリトライされる/されない。"""
        task = BackgroundTask(
            func=_raise_value_error,
            max_retries=1,
            retry_delay=0.1,
            start_method="forkserver",
            retry_on_exception=retry_on_exception,
        )
        with pytest.raises(TaskError) as exc_info:
            task.run()
        assert isinstance(exc_info.value, MaxRetriesExceededError) == expect_max_retries_exceeded


# ---- os._exit 系 ----
class TestOsExit:
    """os._exit() による強制終了シナリオのテスト。"""

    @staticmethod
    def test_raises_task_error_on_os_exit() -> None:
        """os._exit() による強制終了時に TaskError が送出される。"""
        task = BackgroundTask(func=_os_exit, start_method="forkserver")
        with pytest.raises(TaskError):
            task.run()

    @staticmethod
    @pytest.mark.parametrize(
        ("retry_on_os_exit", "expect_max_retries_exceeded"),
        [
            pytest.param(True, True, id="retried"),
            pytest.param(False, False, id="not_retried"),
        ],
    )
    def test_os_exit_retry_behavior(retry_on_os_exit: bool, expect_max_retries_exceeded: bool) -> None:
        """retry_on_os_exit の設定によりリトライされる/されない。"""
        task = BackgroundTask(
            func=_os_exit,
            max_retries=1,
            retry_delay=0.1,
            start_method="forkserver",
            retry_on_os_exit=retry_on_os_exit,
        )
        with pytest.raises(TaskError) as exc_info:
            task.run()
        assert isinstance(exc_info.value, MaxRetriesExceededError) == expect_max_retries_exceeded


# ---- retry_signals ----
class TestRetrySignals:
    """retry_signals パラメータのテスト。"""

    @staticmethod
    @pytest.mark.parametrize(
        ("retry_signals", "expect_max_retries_exceeded"),
        [
            pytest.param(True, True, id="all_signals_retried"),
            pytest.param(False, False, id="no_signals_not_retried"),
        ],
    )
    def test_signal_retry_behavior(retry_signals: bool, expect_max_retries_exceeded: bool) -> None:
        """retry_signals の True/False でリトライされる/されない。"""
        task = BackgroundTask(
            func=_send_sigterm,
            max_retries=1,
            retry_delay=0.1,
            start_method="forkserver",
            retry_signals=retry_signals,
        )
        with pytest.raises(TaskError) as exc_info:
            task.run()
        assert isinstance(exc_info.value, MaxRetriesExceededError) == expect_max_retries_exceeded

    @staticmethod
    def test_specific_signal_retried() -> None:
        """指定シグナルにマッチする場合はリトライされる。"""
        task = BackgroundTask(
            func=_send_sigterm,
            max_retries=1,
            retry_delay=0.1,
            start_method="forkserver",
            retry_signals={-signal.SIGTERM.value},
        )
        with pytest.raises(MaxRetriesExceededError):
            task.run()

    @staticmethod
    def test_non_matching_signal_not_retried() -> None:
        """指定シグナルにマッチしない場合はリトライされない。"""
        task = BackgroundTask(
            func=_send_sigterm,  # SIGTERM = -15
            max_retries=1,
            retry_delay=0.1,
            start_method="forkserver",
            retry_signals={-9},  # SIGKILL のみ → SIGTERM はマッチしない
        )
        with pytest.raises(TaskError) as exc_info:
            task.run()
        assert not isinstance(exc_info.value, MaxRetriesExceededError)

    @staticmethod
    def test_default_retries_on_sigkill() -> None:
        """デフォルト設定 (retry_signals={-9}) で SIGKILL はリトライされる。"""
        task = BackgroundTask(
            func=_send_sigkill,
            max_retries=1,
            retry_delay=0.1,
            start_method="forkserver",
        )
        with pytest.raises(MaxRetriesExceededError):
            task.run()


# ---- キャンセル ----
class TestCancel:
    """キャンセルシナリオのテスト。"""

    @staticmethod
    def test_cancel_stops_task() -> None:
        """cancel() でタスクが停止しステータスが CANCELLED になる。"""
        task = BackgroundTask(
            func=_succeed,
            args=(30.0,),
            start_method="forkserver",
        )
        task.start()
        time.sleep(0.3)
        task.cancel()
        task.wait()
        assert task.status == TaskStatus.CANCELLED

    @staticmethod
    def test_wait_returns_normally_after_cancel() -> None:
        """キャンセル後の wait() は例外なしで返る。"""
        task = BackgroundTask(
            func=_succeed,
            args=(30.0,),
            start_method="forkserver",
        )
        task.start()
        time.sleep(0.3)
        task.cancel()
        task.wait()

    @staticmethod
    def test_cancel_during_retry_delay() -> None:
        """リトライ待機中のキャンセルでステータスが CANCELLED になる。"""
        task = BackgroundTask(
            func=_raise_value_error,
            max_retries=3,
            retry_delay=10.0,
            poll_interval=0.1,
            start_method="forkserver",
            retry_on_exception=True,
        )
        task.start()
        time.sleep(0.5)  # 1回失敗してリトライ待機に入るまで待つ
        task.cancel()
        task.wait()
        assert task.status == TaskStatus.CANCELLED


# ---- API バリデーション ----
class TestApiValidation:
    """API のバリデーションテスト。"""

    @staticmethod
    def test_invalid_start_method_raises_value_error() -> None:
        """不正な start_method で ValueError が送出される。"""
        with pytest.raises(ValueError, match="start_method"):
            BackgroundTask(func=_succeed, start_method="fork")  # type: ignore[arg-type]

    @staticmethod
    def test_double_start_raises_runtime_error() -> None:
        """start() の二重呼び出しで RuntimeError が送出される。"""
        task = BackgroundTask(func=_succeed, args=(30.0,), start_method="forkserver")
        task.start()
        with pytest.raises(RuntimeError):
            task.start()
        task.cancel()
        task.wait()

    @staticmethod
    def test_wait_before_start_raises_runtime_error() -> None:
        """start() 前の wait() 呼び出しで RuntimeError が送出される。"""
        task = BackgroundTask(func=_succeed, start_method="forkserver")
        with pytest.raises(RuntimeError):
            task.wait()

    @staticmethod
    def test_wait_timeout_raises_timeout_error() -> None:
        """タイムアウト時に TimeoutError が送出される。"""
        task = BackgroundTask(func=_succeed, args=(30.0,), start_method="forkserver")
        task.start()
        with pytest.raises(TimeoutError):
            task.wait(timeout=0.1)
        task.cancel()
        task.wait()

    @staticmethod
    def test_auto_start_method_does_not_raise() -> None:
        """start_method='auto' で正常終了する。"""
        task = BackgroundTask(func=_succeed, start_method="auto")
        task.run()
        assert task.status == TaskStatus.COMPLETED


# ---- 例外クラス ----
class TestExceptionClasses:
    """例外クラスのテスト。"""

    @staticmethod
    def test_task_error_str_with_traceback() -> None:
        """トレースバックあり TaskError の文字列表現にワーカートレースバックが含まれる。"""
        err = TaskError("失敗", original_traceback="Traceback...")
        assert "ワーカートレースバック" in str(err)
        assert "Traceback..." in str(err)

    @staticmethod
    def test_task_error_str_without_traceback() -> None:
        """トレースバックなし TaskError の文字列表現がメッセージのみ。"""
        err = TaskError("失敗")
        assert str(err) == "失敗"

    @staticmethod
    def test_max_retries_exceeded_is_subclass() -> None:
        """MaxRetriesExceededError は TaskError のサブクラス。"""
        err = MaxRetriesExceededError("失敗")
        assert isinstance(err, TaskError)


# ---- _resolve_start_method ----
class TestResolveStartMethod:
    """_resolve_start_method のユニットテスト。"""

    @staticmethod
    def test_spawn_resolves_to_spawn() -> None:
        """'spawn' はそのまま 'spawn' に解決される。"""
        assert _resolve_start_method("spawn") == "spawn"

    @staticmethod
    def test_forkserver_resolves_to_forkserver() -> None:
        """'forkserver' はそのまま 'forkserver' に解決される。"""
        assert _resolve_start_method("forkserver") == "forkserver"

    @staticmethod
    def test_auto_resolves_to_forkserver_on_linux() -> None:
        """Linux 環境で 'auto' は 'forkserver' に解決される。"""
        if platform.system() == "Windows":
            pytest.skip("Linux のみ")
        assert _resolve_start_method("auto") == "forkserver"

    @staticmethod
    def test_invalid_raises_value_error() -> None:
        """無効な値で ValueError が送出される。"""
        with pytest.raises(ValueError, match="start_method"):
            _resolve_start_method("fork")  # type: ignore[arg-type]


# ---- _describe_exitcode ----
class TestDescribeExitcode:
    """_describe_exitcode のユニットテスト。"""

    @staticmethod
    def test_positive_returns_exitcode_str() -> None:
        """正の終了コードは 'exitcode=N' 形式になる。"""
        assert _describe_exitcode(1) == "exitcode=1"

    @staticmethod
    def test_signal_returns_signal_name() -> None:
        """シグナルによる終了はシグナル名を含む文字列になる。"""
        result: str = _describe_exitcode(-signal.SIGTERM.value)
        assert "SIGTERM" in result

    @staticmethod
    def test_unknown_negative_returns_exitcode_str() -> None:
        """不明なシグナル番号は 'exitcode=N' 形式にフォールバックする。"""
        assert _describe_exitcode(-999) == "exitcode=-999"
