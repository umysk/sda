# Copyright (c) 2026 U
"""BackgroundTask クラスおよび関連ユーティリティの定義。"""

import enum
import logging
import logging.handlers
import multiprocessing
import multiprocessing.queues
import platform
import queue
import signal
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from _thread import lock
    from multiprocessing.context import ForkServerContext, ForkServerProcess, SpawnContext, SpawnProcess

from ._exceptions import MaxRetriesExceededError, TaskError
from ._worker import run as _worker_run

# デフォルトのリトライ対象シグナル: SIGKILL (-9) のみ (OOM killer)
_RETRY_SIGNALS_DEFAULT: frozenset[int] = frozenset({-signal.SIGKILL.value})

# ---- ステータス定義 ----


class TaskStatus(enum.Enum):
    """バックグラウンドタスクの実行状態。

    Attributes
    ----------
    PENDING : str
        未開始。
    RUNNING : str
        実行中。
    RETRYING : str
        リトライ待機中。
    COMPLETED : str
        正常終了。
    ERROR : str
        最大リトライ到達後のエラー終了。
    CANCELLED : str
        キャンセルにより終了。

    """

    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


# ---- 内部ユーティリティ ----


def _resolve_start_method(
    start_method: Literal["auto", "spawn", "forkserver"],
) -> Literal["spawn", "forkserver"]:
    """start_method 文字列を解決する。

    Parameters
    ----------
    start_method : str
        'auto', 'spawn', 'forkserver' のいずれか。

    Returns
    -------
    str
        実際に使用する開始方式。

    Raises
    ------
    ValueError
        無効な start_method が指定された場合。

    """
    if start_method == "auto":
        return "spawn" if platform.system() == "Windows" else "forkserver"
    if start_method not in {"spawn", "forkserver"}:
        msg: str = f"start_method は 'auto', 'spawn', 'forkserver' のいずれかを指定してください: {start_method!r}"
        raise ValueError(msg)
    return start_method


def _describe_exitcode(exitcode: int) -> str:
    """Exitcode を人間が読めるテキストに変換する。

    Parameters
    ----------
    exitcode : int
        multiprocessing.Process.exitcode の値。

    Returns
    -------
    str
        終了理由の説明文。

    """
    if exitcode > 0:
        return f"exitcode={exitcode}"
    # 負値 = シグナルによる強制終了
    try:
        sig_name: str = signal.Signals(-exitcode).name
    except (ValueError, OSError):
        return f"exitcode={exitcode}"
    else:
        return f"シグナル {sig_name} で強制終了 (exitcode={exitcode})"


class _LogForwarder(logging.Handler):
    """ワーカーキューから受け取った LogRecord をメインプロセスのロガーへ転送するハンドラー。

    Parameters
    ----------
    logger : logging.Logger
        転送先のロガー。

    """

    def __init__(self, logger: logging.Logger) -> None:
        super().__init__()
        self._logger: logging.Logger = logger

    def emit(self, record: logging.LogRecord) -> None:
        """レコードをメインプロセスのロガーへ転送する。

        Parameters
        ----------
        record : logging.LogRecord
            転送するログレコード。

        """
        self._logger.handle(record)


# ---- メインクラス ----


class BackgroundTask:
    """関数をバックグラウンドプロセスで実行するラッパー。

    モニタースレッドがワーカープロセスを監視し、
    ゾンビ検知・リトライ・ログ転送を担う。

    Parameters
    ----------
    func : Callable[..., Any]
        実行する関数。pickle 可能 (spawn / forkserver の制約) である必要がある。
    args : tuple[Any, ...], optional
        func に渡す位置引数。デフォルトは空タプル。
    kwargs : dict[str, Any], optional
        func に渡すキーワード引数。デフォルトは空辞書。
    max_retries : int, optional
        失敗時のリトライ上限回数。0 = リトライなし。デフォルトは 0。
    retry_delay : float, optional
        リトライ前の待機時間 (秒)。デフォルトは 5.0。
    poll_interval : float, optional
        ワーカーの生存確認・ゾンビ検知のポーリング間隔 (秒)。デフォルトは 1.0。
    start_method : str, optional
        プロセス起動方式。'auto' (デフォルト)、'spawn'、'forkserver' のいずれか。
        'auto' の場合、Windows では 'spawn'、それ以外では 'forkserver' を使用する。
    retry_on_exception : bool, optional
        Python 例外 (raise) 発生時にリトライするか。デフォルトは False。
    retry_on_os_exit : bool, optional
        os._exit() による終了時にリトライするか。デフォルトは False。
    retry_signals : bool or set[int], optional
        シグナルによる強制終了時のリトライ設定。
        True = 全シグナルでリトライ、False = リトライしない、
        set[int] = 指定した exitcode のみリトライ。
        デフォルトは {-9} (SIGKILL = OOM killer のみ)。
    logger : logging.Logger, optional
        使用するロガー。省略時は ``logging.getLogger('bgrun')`` を使用する。

    Examples
    --------
    >>> import logging
    >>> import bgrun
    >>>
    >>> logging.basicConfig(level=logging.INFO)
    >>>
    >>> def heavy_task():
    ...     import time; time.sleep(2)
    ...
    >>> task = bgrun.BackgroundTask(func=heavy_task, max_retries=2)
    >>> try:
    ...     task.run()
    ... except bgrun.TaskError as e:
    ...     print(e)

    """

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        func: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        max_retries: int = 0,
        retry_delay: float = 5.0,
        poll_interval: float = 1.0,
        start_method: Literal["auto", "spawn", "forkserver"] = "auto",
        *,
        retry_on_exception: bool = False,
        retry_on_os_exit: bool = False,
        retry_signals: bool | set[int] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._func: Callable[..., Any] = func
        self._args: tuple[Any, ...] = args
        self._kwargs: dict[str, Any] = kwargs or {}
        self._max_retries: int = max_retries
        self._retry_delay: float = retry_delay
        self._poll_interval: float = poll_interval
        self._start_method: Literal["spawn", "forkserver"] = _resolve_start_method(start_method)
        self._retry_on_exception: bool = retry_on_exception
        self._retry_on_os_exit: bool = retry_on_os_exit
        if retry_signals is None:
            self._retry_signals: bool | frozenset[int] = _RETRY_SIGNALS_DEFAULT
        elif isinstance(retry_signals, bool):
            self._retry_signals = retry_signals
        else:
            self._retry_signals = frozenset(retry_signals)
        self._logger: logging.Logger = logger or logging.getLogger("bgrun")

        self._status = TaskStatus.PENDING
        self._status_lock: lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._done_event = threading.Event()
        self._stored_error: TaskError | None = None
        self._monitor_thread: threading.Thread | None = None

    # ---- 公開プロパティ ----

    @property
    def status(self) -> TaskStatus:
        """現在のタスクステータス。スレッドセーフ。"""
        with self._status_lock:
            return self._status

    # ---- 公開メソッド ----

    def start(self) -> None:
        """バックグラウンドタスクを開始する (ノンブロッキング)。

        Raises
        ------
        RuntimeError
            既に start() が呼ばれている場合。

        """
        if self._monitor_thread is not None:
            msg = "タスクは既に開始されています"
            raise RuntimeError(msg)
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name=f"bgrun-monitor-{self._func.__name__}",
        )
        self._monitor_thread.start()

    def wait(self, timeout: float | None = None) -> None:
        """タスクの完了まで待機する (ブロッキング)。

        正常終了またはキャンセル時は正常リターン。
        失敗時は例外を送出する。

        Parameters
        ----------
        timeout : float, optional
            最大待機時間 (秒)。省略時は無制限に待機する。

        Raises
        ------
        RuntimeError
            start() を呼ぶ前に wait() が呼ばれた場合。
        TimeoutError
            timeout 以内にタスクが完了しなかった場合。

        """
        if self._monitor_thread is None:
            msg: str = "タスクが開始されていません。先に start() を呼んでください"
            raise RuntimeError(msg)
        if not self._done_event.wait(timeout=timeout):
            msg: str = f"タスクが {timeout}s 以内に完了しませんでした"
            raise TimeoutError(msg)
        if self._stored_error is not None:
            raise self._stored_error

    def run(self) -> None:
        """start() と wait() を連続実行するショートハンド。

        失敗時は TaskError またはそのサブクラスが送出される。

        """
        self.start()
        self.wait()

    def cancel(self) -> None:
        """キャンセルを要求する (ノンブロッキング)。

        実際の停止は非同期で行われる。
        wait() はキャンセル後に正常リターンする。
        """
        self._cancel_event.set()

    # ---- 内部実装 ----

    def _set_status(self, status: TaskStatus) -> None:
        with self._status_lock:
            self._status: TaskStatus = status

    def _start_log_listener(
        self, log_queue: multiprocessing.queues.Queue[logging.LogRecord]
    ) -> logging.handlers.QueueListener:
        """ワーカーのログキューを監視するリスナーを起動する。

        Parameters
        ----------
        log_queue : multiprocessing.queues.Queue[logging.LogRecord]
            ワーカーが LogRecord を書き込むキュー。

        Returns
        -------
        logging.handlers.QueueListener
            起動済みのリスナー。使用後は stop() を呼ぶこと。

        """
        listener = logging.handlers.QueueListener(
            log_queue,
            _LogForwarder(self._logger),
            respect_handler_level=True,
        )
        listener.start()
        return listener

    def _interruptible_sleep(self, duration: float) -> None:
        """キャンセルイベントで中断可能なスリープ。

        Parameters
        ----------
        duration : float
            最大スリープ時間 (秒)。

        """
        deadline: float = time.monotonic() + duration
        while time.monotonic() < deadline:
            if self._cancel_event.is_set():
                return
            time.sleep(min(0.5, deadline - time.monotonic()))

    def _should_retry(self, exitcode: int, error_info: dict[str, str] | None) -> bool:
        """終了原因に基づいてリトライすべきか判定する。

        Parameters
        ----------
        exitcode : int
            ワーカーの終了コード。
        error_info : dict[str, str] or None
            error_queue から取得したエラー情報。Python 例外の場合は存在する。

        Returns
        -------
        bool
            リトライすべき場合は True。

        """
        if error_info is not None:
            # Python 例外 (raise → sys.exit(1) → error_queue にデータあり)
            return self._retry_on_exception
        if exitcode < 0:
            # シグナルによる強制終了 (exitcode = -シグナル番号)
            if isinstance(self._retry_signals, bool):
                return self._retry_signals
            return exitcode in self._retry_signals
        # os._exit(N): exitcode > 0 かつ error_queue 空
        return self._retry_on_os_exit

    @staticmethod
    def _drain_error_queue(error_queue: multiprocessing.queues.Queue[dict[str, str]]) -> dict[str, str] | None:
        """error_queue からエラー情報を取り出す。

        Parameters
        ----------
        error_queue : multiprocessing.queues.Queue[dict[str, str]]
            ワーカーがエラー情報を書き込んだキュー。

        Returns
        -------
        dict[str, str] or None
            エラー情報辞書、またはキューが空の場合は None。

        """
        try:
            return error_queue.get_nowait()
        except queue.Empty:
            return None

    def _handle_abnormal_exit(
        self,
        exitcode: int,
        error_info: dict[str, str] | None,
        retry_count: int,
    ) -> TaskError:
        """異常終了時のエラーオブジェクトを生成してログ出力する。

        Parameters
        ----------
        exitcode : int
            ワーカーの終了コード。
        error_info : dict[str, str] or None
            error_queue から取得したエラー情報。存在しない場合は None。
        retry_count : int
            これまでのリトライ回数 (0 = 初回失敗)。

        Returns
        -------
        TaskError
            生成したエラーオブジェクト。

        """
        exit_desc: str = _describe_exitcode(exitcode)

        if error_info:
            self._logger.error(
                "ワーカーで例外が発生しました: %s: %s\n%s",
                error_info["type"],
                error_info["message"],
                error_info["traceback"],
            )
            msg = f"{error_info['type']}: {error_info['message']}"
            tb: str = error_info.get("traceback", "")
        else:
            self._logger.error(
                "ワーカーが予期せず終了しました: %s (例外情報なし、ログを確認してください)",
                exit_desc,
            )
            msg: str = f"ワーカーが予期せず終了しました: {exit_desc}"
            tb: str = ""

        if retry_count > 0:
            error_msg: str = f"{retry_count} 回リトライ後もタスクが失敗しました。最後のエラー: {msg}"
            err: TaskError = MaxRetriesExceededError(
                error_msg,
                original_traceback=tb,
            )
        else:
            err = TaskError(msg, original_traceback=tb)

        return err

    def _monitor_loop(self) -> None:
        """モニタースレッドのメインループ。

        ワーカープロセスの起動・監視・ゾンビ回収・リトライを管理する。
        is_alive() のポーリングが内部で waitpid(WNOHANG) を呼ぶため、
        ゾンビプロセスは次のポーリングで自動回収される。
        """
        ctx: SpawnContext | ForkServerContext = cast(
            "SpawnContext | ForkServerContext", multiprocessing.get_context(self._start_method)
        )
        retry_count = 0

        while True:
            # ---- ワーカー起動 ----
            error_queue: multiprocessing.queues.Queue[dict[str, str]] = ctx.Queue()
            log_queue: multiprocessing.queues.Queue[logging.LogRecord] = ctx.Queue()

            process: ForkServerProcess | SpawnProcess = ctx.Process(
                target=_worker_run,
                args=(self._func, self._args, self._kwargs, error_queue, log_queue),
                daemon=False,
            )
            process.start()
            log_listener: logging.handlers.QueueListener = self._start_log_listener(log_queue)

            attempt: int = retry_count + 1
            total: int = self._max_retries + 1
            self._set_status(TaskStatus.RUNNING)
            self._logger.info(
                "ワーカー起動: pid=%s, 試行 %s/%s (start_method=%s)",
                process.pid,
                attempt,
                total,
                self._start_method,
            )

            # ---- 監視ループ ----
            # is_alive() が内部で waitpid(WNOHANG) を呼ぶため、
            # ゾンビはこのポーリングで随時回収される
            while process.is_alive():
                time.sleep(self._poll_interval)

                if self._cancel_event.is_set():
                    process.terminate()
                    process.join(timeout=5)
                    if process.is_alive():
                        process.kill()
                    process.join()  # 念のためゾンビ回収
                    log_listener.stop()
                    self._set_status(TaskStatus.CANCELLED)
                    self._logger.info("タスクをキャンセルしました")
                    self._done_event.set()
                    return

            # ---- プロセス終了後の処理 ----
            process.join()  # 確実にゾンビ回収
            log_listener.stop()  # 残ログを全て処理してから停止
            exitcode: int = cast("int", process.exitcode)  # join() 後は必ず int

            if exitcode == 0:
                self._set_status(TaskStatus.COMPLETED)
                self._logger.info("タスクが正常終了しました")
                self._done_event.set()
                return

            # ---- 異常終了 ----
            error_info: dict[str, str] | None = self._drain_error_queue(error_queue)

            if retry_count < self._max_retries and self._should_retry(exitcode, error_info):
                # リトライ
                exit_desc: str = _describe_exitcode(exitcode)
                retry_count += 1
                self._set_status(TaskStatus.RETRYING)
                self._logger.warning(
                    "ワーカーが異常終了しました (%s)。リトライ %s/%s を %ss 後に実行します",
                    exit_desc,
                    retry_count,
                    self._max_retries,
                    self._retry_delay,
                )
                if error_info:
                    self._logger.warning(
                        "前回のエラー: %s: %s",
                        error_info["type"],
                        error_info["message"],
                    )
                self._interruptible_sleep(self._retry_delay)
                if self._cancel_event.is_set():
                    self._set_status(TaskStatus.CANCELLED)
                    self._logger.info("リトライ待機中にキャンセルされました")
                    self._done_event.set()
                    return
            else:
                # 最大リトライ到達 → エラー確定
                err: TaskError = self._handle_abnormal_exit(exitcode, error_info, retry_count)
                self._stored_error = err
                self._set_status(TaskStatus.ERROR)
                self._done_event.set()
                return
