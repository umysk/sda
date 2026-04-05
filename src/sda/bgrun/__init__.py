# Copyright (c) 2026 U
"""bgrun : バックグラウンドプロセス実行ライブラリ。

長時間かかる処理を spawn / forkserver で起動したサブプロセスで実行し、
ゾンビ検知・自動回収・リトライ・ログ転送を提供する

Examples
--------
>>> import logging
>>> import sda
>>>
>>> logging.basicConfig(level=logging.INFO)
>>>
>>> def heavy(n: int) -> None:
...     import time; time.sleep(n)
...
>>> task = sda.BackgroundTask(
...     func=heavy,
...     args=(5,),
...     max_retries=2,
...     retry_delay=3.0,
... )
>>> try:
...     task.run()           # start() + wait() のショートハンド
... except sda.MaxRetriesExceededError as e:
...     print(f"失敗: {e}")

"""

from ._exceptions import MaxRetriesExceededError, TaskError
from ._task import BackgroundTask, TaskStatus

__all__: list[str] = [
    "BackgroundTask",
    "MaxRetriesExceededError",
    "TaskError",
    "TaskStatus",
]
