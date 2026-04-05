# Copyright (c) 2026 U
class TaskError(Exception):
    """バックグラウンドタスクの失敗を表す例外。

    Parameters
    ----------
    message : str
        エラーの概要メッセージ。
    original_traceback : str, optional
        ワーカープロセスで発生した例外のトレースバック文字列。

    """

    def __init__(self, message: str, original_traceback: str = "") -> None:
        super().__init__(message)
        self.original_traceback: str = original_traceback

    def __str__(self) -> str:
        base: str = super().__str__()
        if self.original_traceback:
            return f"{base}\n--- ワーカートレースバック ---\n{self.original_traceback}"
        return base


class MaxRetriesExceededError(TaskError):
    """最大リトライ回数に達してもタスクが失敗した場合に送出される例外。

    Parameters
    ----------
    message : str
        エラーの概要メッセージ。
    original_traceback : str, optional
        最後のリトライで発生した例外のトレースバック文字列。

    """
