# log

アプリケーションのエントリーポイントで `setup()` を1回呼ぶことで、
root logger にハンドラーとフォーマットをまとめて設定するサブモジュール。


## クイックスタート

```python
import logging
import sda.log

sda.log.setup(console_level="INFO", file_level="DEBUG")

# 各モジュールでは標準ライブラリをそのまま使う
logger = logging.getLogger(__name__)
logger.info("起動しました")
```


## API リファレンス

### setup()

```python
sda.log.setup(
    fmt="default",          # フォーマットプリセット
    console_level="INFO",   # コンソール出力レベル (None = コンソール出力なし)
    file_level=None,        # ファイル出力レベル   (None = ファイル出力なし)
    file_name="logs/app.log",  # file_level が None でなければ使用
)
```

#### パラメータ一覧

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `fmt` | `FmtName` | `"default"` | フォーマットプリセット名。詳細は「[フォーマットプリセット](#フォーマットプリセット)」参照。 |
| `console_level` | `str \| int \| None` | `"INFO"` | コンソール (stderr) ハンドラーのログレベル。`None` のときコンソールへ出力しない。 |
| `file_level` | `str \| int \| None` | `None` | ファイルハンドラーのログレベル。`None` のときファイルへ出力しない。 |
| `file_name` | `str \| Path` | `"logs/app.log"` | ログファイルのパス。`file_level` が `None` のときは無視される。ファイル名の先頭にタイムスタンプ (JST) を付加する。存在しない親ディレクトリは自動作成される。 |

#### root logger レベルの自動設定

root logger のレベルは有効なハンドラーレベルの最小値に自動設定される。
ハンドラーごとに個別のレベルで絞り込みが行われる。

```
console_level="WARNING", file_level="DEBUG" のとき

root_logger (DEBUG)  ← min("WARNING", "DEBUG") に自動設定
    ├── console_handler (WARNING) → WARNING 以上をコンソールへ
    └── file_handler    (DEBUG)   → DEBUG 以上をファイルへ
```

#### ファイル名のタイムスタンプ付加

`file_level` を指定すると、ファイル名の先頭に `YYYYmmddHHMMSS_` が付加される（JST）。

```
"logs/app.log" → "logs/20260405123912_app.log"
```

#### 複数回呼び出し

`setup()` を複数回呼び出した場合、既存のハンドラーを破棄して上書きする。

#### 両方 None のとき

`console_level` と `file_level` が両方 `None` のとき `ValueError` を raise する。

### フォーマットプリセット

| 名前 | 出力例 |
|------|--------|
| `"default"` | `2026-04-05 12:00:00.123 [INFO] PID:1234 myapp: メッセージ` |
| `"simple"` | `[INFO] メッセージ` |
| `"detailed"` | `2026-04-05 12:00:00.123 [INFO] PID:1234 Thread:MainThread myapp (log_example.py:42): メッセージ` |


## 使用パターン

### コンソールのみ

```python
sda.log.setup(console_level="INFO")
```

### コンソールとファイルに同時出力

コンソールは `INFO` 以上、ファイルには `DEBUG` 以上を記録する。

```python
sda.log.setup(
    console_level="INFO",
    file_level="DEBUG",
    file_name="output/logs/app.log",
)
```

### ファイルのみ

```python
sda.log.setup(
    console_level=None,
    file_level="DEBUG",
    file_name="output/logs/app.log",
)
```

### bgrun と組み合わせる

```python
import logging
import sda
import sda.log

sda.log.setup(console_level="INFO", file_level="DEBUG", file_name="output/logs/app.log")

def heavy_task(n: int) -> None:
    import time
    time.sleep(n)

task = sda.BackgroundTask(
    func=heavy_task,
    args=(5,),
    logger=logging.getLogger(__name__),
)
task.run()
```

> ワーカープロセスのログも `setup()` で設定したハンドラーへ転送される。


## logging の仕組み

`setup()` は root logger を設定する。各モジュールで取得するロガーはツリー構造になっており、
レコードは自動的に root logger へ伝播するため、各モジュール側での設定は不要。

```
root logger  ← setup() でハンドラーを設定
├── "sda.bgrun"
├── "myapp"
└── "myapp.sub"      ← getLogger(__name__) で取得
```

```python
# 各モジュールはこれだけ書けばよい
import logging
logger = logging.getLogger(__name__)
```

> ライブラリ側（`sda`, `bgrun` など）では `setup()` を呼ばない。
> アプリのエントリーポイントで1回だけ呼ぶこと。


## ファイル構成

```
src/sda/
└── log.py            # setup() の実装

docs/
└── log.md            # このドキュメント

examples/
└── log_example.py    # 全シナリオの動作確認サンプル

tests/log/
└── test_setup.py     # setup() のユニットテスト
```


## 動作確認サンプル

```bash
uv run python examples/log_example.py console   # シナリオ1: コンソールのみ
uv run python examples/log_example.py filtered  # シナリオ2: コンソールを WARNING 以上に絞る
uv run python examples/log_example.py file      # シナリオ3: ファイルのみ
uv run python examples/log_example.py both      # シナリオ4: コンソール + ファイル
uv run python examples/log_example.py fmt       # シナリオ5: フォーマットプリセット比較
uv run python examples/log_example.py all       # 全シナリオ
```


## 付録: logging モジュール パラメータ参考

> 保守時の参考用。全一覧: https://docs.python.org/3/library/logging.html#logrecord-attributes

### ログレベル

| 定数 | 数値 | 用途 |
|---|---|---|
| `logging.DEBUG` | 10 | 詳細なデバッグ情報 |
| `logging.INFO` | 20 | 一般的な情報 |
| `logging.WARNING` | 30 | 警告メッセージ |
| `logging.ERROR` | 40 | エラーメッセージ |
| `logging.CRITICAL` | 50 | 致命的なエラー |

### フォーマット指定子

| 指定子 | 型 | 内容 |
|---|---|---|
| `%(asctime)s` | str | タイムスタンプ（`datefmt` で書式指定） |
| `%(msecs)d` | int | ミリ秒 |
| `%(name)s` | str | ロガー名 |
| `%(levelname)s` | str | ログレベル名（DEBUG / INFO など） |
| `%(levelno)d` | int | ログレベル番号 |
| `%(message)s` | str | ログメッセージ |
| `%(filename)s` | str | ファイル名 |
| `%(pathname)s` | str | ファイルのフルパス（`__file__` と同じ値） |
| `%(module)s` | str | モジュール名 |
| `%(funcName)s` | str | 関数名 |
| `%(lineno)d` | int | 行番号 |
| `%(created)f` | float | 作成時刻（Unix タイムスタンプ） |
| `%(thread)d` | int | スレッド ID |
| `%(threadName)s` | str | スレッド名 |
| `%(process)d` | int | プロセス ID (PID) |

### ハンドラー

| クラス | 出力先 |
|---|---|
| `StreamHandler` | コンソール（stderr など） |
| `FileHandler` | ファイル |
| `RotatingFileHandler` | ファイル（サイズでローテーション） |
| `TimedRotatingFileHandler` | ファイル（時間でローテーション） |
