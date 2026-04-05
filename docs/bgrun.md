# bgrun

長時間かかる処理を spawn / forkserver で起動したサブプロセスで実行し、
ゾンビ検知・自動回収・リトライ・ログ転送を提供するサブパッケージ。


## クイックスタート

```python
import logging
import sda

logging.basicConfig(level=logging.INFO)

def heavy_task(n: int) -> None:
    import time
    time.sleep(n)

task = sda.BackgroundTask(
    func=heavy_task,
    args=(5,),
    max_retries=2,
    retry_delay=3.0,
)

try:
    task.run()  # start() + wait() のショートハンド
except sda.MaxRetriesExceededError as e:
    print(f"失敗: {e}")
```

> `sda.bgrun.BackgroundTask` としてもアクセスできる。


## API リファレンス

### BackgroundTask

#### コンストラクタ

```python
task = sda.BackgroundTask(
    func=my_func,                  # 必須。pickle 可能な関数
    args=(1, 2),                   # 省略可 (デフォルト: ())
    kwargs={"k": "v"},             # 省略可 (デフォルト: {})
    max_retries=3,                 # 省略可 (デフォルト: 0 = リトライなし)
    retry_delay=5.0,               # 省略可 (デフォルト: 5.0 秒)
    poll_interval=1.0,             # 省略可 (デフォルト: 1.0 秒)
    start_method="auto",           # 省略可 (デフォルト: "auto")
    retry_on_exception=False,      # 省略可 (デフォルト: False)
    retry_on_os_exit=False,        # 省略可 (デフォルト: False)
    retry_signals={-9},            # 省略可 (デフォルト: {-9} = SIGKILL のみ)
    logger=logger,                 # 省略可 (デフォルト: logging.getLogger("bgrun"))
)
```

#### パラメータ一覧

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `func` | `Callable` | 必須 | 実行する関数。pickle 可能（spawn・forkserver の制約）であること。ラムダ・ネスト関数は不可。 |
| `args` | `tuple` | `()` | `func` に渡す位置引数。 |
| `kwargs` | `dict` | `{}` | `func` に渡すキーワード引数。 |
| `max_retries` | `int` | `0` | 失敗時のリトライ上限回数。`0` = リトライなし。 |
| `retry_delay` | `float` | `5.0` | リトライ前の待機時間（秒）。キャンセルイベントで中断される。 |
| `poll_interval` | `float` | `1.0` | ワーカーの生存確認ポーリング間隔（秒）。小さいほど応答が速くなるが CPU 使用率が上がる。 |
| `start_method` | `str` | `"auto"` | プロセス起動方式。詳細は「[start_method](#start_method)」参照。 |
| `retry_on_exception` | `bool` | `False` | Python 例外（`raise`）でワーカーが終了した場合にリトライするか。 |
| `retry_on_os_exit` | `bool` | `False` | `os._exit(N)` でワーカーが強制終了した場合にリトライするか。 |
| `retry_signals` | `bool \| set[int]` | `{-9}` | シグナル終了時のリトライ設定。`True` = 全シグナル、`False` = なし、`set[int]` = 指定した exitcode のみ（例: `{-9}` = SIGKILL のみ）。 |
| `logger` | `logging.Logger` | `logging.getLogger("bgrun")` | タスクのログ出力先ロガー。ワーカーのログもこのロガーへ転送される。 |

#### メソッド・プロパティ

| 名前 | シグネチャ | 説明 |
|---|---|---|
| `start()` | `() -> None` | バックグラウンドタスクを開始する（ノンブロッキング）。 |
| `wait()` | `(timeout: float \| None = None) -> None` | タスクの完了まで待機する（ブロッキング）。失敗時は例外を送出。 |
| `cancel()` | `() -> None` | キャンセルを要求する（ノンブロッキング）。`wait()` は正常リターン。 |
| `run()` | `() -> None` | `start()` + `wait()` のショートハンド。 |
| `status` | `TaskStatus` | 現在のタスクステータス（読み取り専用・スレッドセーフ）。 |

### start_method

| 値 | 動作 |
|----|------|
| `"auto"` | Windows では `"spawn"`、それ以外では `"forkserver"` |
| `"spawn"` | 毎回新しい Python インタープリタを起動 |
| `"forkserver"` | 専用サーバープロセスから fork（2 回目以降が高速） |

### リトライ制御

| パラメータ | デフォルト | リトライ対象 |
|---|---|---|
| `retry_on_exception` | `False` | Python 例外（`raise`） |
| `retry_on_os_exit` | `False` | `os._exit(N)` |
| `retry_signals` | `{-9}` | シグナル終了。`True` = 全シグナル、`False` = なし、`set[int]` = 指定シグナルのみ |

- デフォルトでは OOM killer（SIGKILL = exitcode `-9`）のみリトライする。
- キャンセルは設定によらずリトライしない。

### TaskStatus

```
PENDING → RUNNING → COMPLETED
                  → RETRYING → RUNNING → ...
                  → ERROR
                  → CANCELLED
```

### 例外クラス

| クラス | 説明 |
|---|---|
| `sda.TaskError` | タスクが失敗した場合に送出される基底例外。`original_traceback` 属性にワーカーのトレースバックを保持する。 |
| `sda.MaxRetriesExceededError` | 最大リトライ回数に達しても失敗した場合に送出される（`TaskError` のサブクラス）。 |

### exitcode の解釈

| exitcode | 原因 |
|----------|------|
| `0` | 正常終了 |
| `> 0` | Python 例外（`sys.exit(1)`）または `os._exit(N)` |
| `< 0` | シグナルによる強制終了（`-9` = SIGKILL / OOM killer） |

`os._exit(N)` の場合は error_queue がフラッシュされないため、例外情報はキューに届かない。
モニタースレッドは「例外情報なし、ログを確認してください」と警告する。


## 制約・注意事項

- `func` は pickle 可能である必要がある（ラムダ・ネスト関数は不可）
- `forkserver` は Windows 非対応のため、Windows では自動的に `spawn` を使用する
- ワーカー内のログは全て `QueueHandler` 経由でメインプロセスへ転送される
- `os._exit()` 呼び出し時は error_queue への書き込みが保証されないが、
  `os._exit()` 前に行われたログ出力は `QueueHandler` 経由で転送される


## 動作確認サンプル

```bash
uv run python examples/bgrun_example.py normal        # シナリオ1: 正常終了
uv run python examples/bgrun_example.py error         # シナリオ2: 例外エラー + リトライ
uv run python examples/bgrun_example.py exit          # シナリオ3: os._exit(1) + リトライ
uv run python examples/bgrun_example.py oom_retry     # シナリオ4: OOM killer + リトライして回復
uv run python examples/bgrun_example.py oom_no_retry  # シナリオ5: OOM killer + リトライなし
uv run python examples/bgrun_example.py oom_exceed    # シナリオ6: OOM killer + リトライ上限超過
uv run python examples/bgrun_example.py cancel        # シナリオ7: キャンセル
uv run python examples/bgrun_example.py all           # 全シナリオ
```


## 開発情報

### 設計前提

- **親プロセスは死なない**（Streamlit 等が常駐）
- 戻り値は受け取らない
- 一時停止機能は不要
- ファイルベースの状態管理は不要

**psutil 不使用の理由:**
`is_alive()` が内部で `os.waitpid(WNOHANG)` を呼ぶため、
ポーリングループだけでゾンビを自動回収できる。

### アーキテクチャ

```
Main Process (Streamlit 等)
├── Main Thread          ← task.start() / wait() / cancel() を呼ぶ
├── Monitor Thread       ← daemon=True。ワーカーを監視・リトライ管理
│     └── QueueListener ← ワーカーのログをメインプロセスのロガーへ転送
└── Worker Process       ← spawn / forkserver で起動。実際の処理を実行
      ├── QueueHandler   ← ルートロガーに設定。全ログを log_queue へ送る
      └── error_queue    ← 例外情報をメインプロセスへ送る
```

### 機能一覧

| 機能 | 詳細 |
|------|------|
| バックグラウンド実行 | `multiprocessing.Process` を spawn / forkserver で起動 |
| 起動方式 | `'auto'`（Windows=spawn, それ以外=forkserver）、`'spawn'`、`'forkserver'` |
| ゾンビ検知・回収 | モニタースレッドがポーリングで `is_alive()` を呼ぶ（内部で `waitpid(WNOHANG)` → 自動回収） |
| リトライ | 失敗時（例外・OOM・os._exit）に指定回数まで再起動。0 = リトライなし |
| キャンセル | `cancel()` 呼び出し → ワーカーを terminate/kill → `wait()` は正常リターン |
| 正常終了 | `wait()` が正常リターン |
| エラー終了 | `wait()` が `TaskError` または `MaxRetriesExceededError` を raise |
| ログ転送 | ワーカーのルートロガーに `QueueHandler` を設定し、メインプロセスへ転送 |

### ファイル構成

```
src/sda/bgrun/
├── __init__.py       # 公開 API
├── _task.py          # BackgroundTask, TaskStatus, _LogForwarder
├── _worker.py        # ワーカープロセスのエントリーポイント
└── _exceptions.py    # TaskError, MaxRetriesExceededError

docs/
└── bgrun.md          # このドキュメント

examples/
└── bgrun_example.py  # 全シナリオの動作確認サンプル（正常・例外・os._exit・OOM・キャンセル）

tests/bgrun/
├── test_task.py      # BackgroundTask の結合テスト
└── test_worker.py    # ワーカープロセスのユニットテスト
```
