# Copyright (c) 2026 U
"""sda.log : ロギング設定ユーティリティ。

アプリケーションのエントリーポイントで setup() を1回呼ぶことで、
root logger にハンドラーとフォーマットを設定する。

Examples
--------
>>> import sda.log
>>> sda.log.setup(console_level="INFO", file_level="DEBUG")

各モジュールでは標準ライブラリをそのまま使う::

    import logging
    logger = logging.getLogger(__name__)

"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Literal, TextIO
from zoneinfo import ZoneInfo

_JST = ZoneInfo("Asia/Tokyo")

FmtName = Literal["default", "simple", "detailed"]

_FORMATS: dict[FmtName, str] = {
    "default": "%(asctime)s.%(msecs)03d [%(levelname)s] PID:%(process)d %(name)s: %(message)s",
    "simple": "[%(levelname)s] %(message)s",
    "detailed": (
        "%(asctime)s.%(msecs)03d [%(levelname)s] PID:%(process)d Thread:%(threadName)s"
        " %(name)s (%(filename)s:%(lineno)d): %(message)s"
    ),
}

_DATEFMT = "%Y-%m-%d %H:%M:%S"
_DEFAULT_FILE_NAME = Path("logs/app.log")


_logger: logging.Logger = logging.getLogger(__name__)


def setup(
    fmt: FmtName = "default",
    console_level: str | int | None = "INFO",
    file_level: str | int | None = None,
    file_name: str | Path = _DEFAULT_FILE_NAME,
    *,
    force: bool = False,
) -> None:
    """Root logger にハンドラーとフォーマットを設定する。

    root logger のレベルは有効なハンドラーレベルの最小値に自動設定される。

    Parameters
    ----------
    fmt : FmtName, optional
        フォーマットプリセット名。"default" | "simple" | "detailed"。
        デフォルトは "default"。
    console_level : str or int or None, optional
        コンソール (stderr) ハンドラーのログレベル。
        None のときコンソールへ出力しない。デフォルトは "INFO"。
    file_level : str or int or None, optional
        ファイルハンドラーのログレベル。
        None のときファイルへ出力しない。デフォルトは None。
    file_name : str or Path, optional
        ログファイルのパス。file_level が None のときは無視される。
        ファイル名の先頭にタイムスタンプ (JST) を付加する。
        存在しない親ディレクトリは自動作成される。
        デフォルトは "logs/app.log"。
        例: "logs/app.log" → "logs/20260405123912_app.log"
    force : bool, optional
        True のとき、既存のハンドラーを閉じて上書きする。
        False のとき、すでに設定済みであれば何もしない。デフォルトは False。

    Raises
    ------
    ValueError
        fmt に未定義のプリセット名が指定された場合。
        console_level と file_level が両方 None の場合。

    Examples
    --------
    >>> import sda.log
    >>> sda.log.setup(console_level="INFO", file_level="DEBUG")

    """
    if fmt not in _FORMATS:
        msg: str = f"fmt は {list(_FORMATS)} のいずれかを指定してください: {fmt!r}"
        raise ValueError(msg)

    if console_level is None and file_level is None:
        msg = "console_level と file_level が両方 None です。少なくとも一方を指定してください。"
        raise ValueError(msg)

    formatter = logging.Formatter(_FORMATS[fmt], datefmt=_DATEFMT)

    root_logger: logging.Logger = logging.getLogger()

    if root_logger.handlers:
        if not force:
            _logger.warning(
                "setup() はすでに設定済みのため無視されました。上書きするには force=True を指定してください。"
            )
            return
        _logger.info("setup() が force=True で呼ばれました。既存のハンドラーを閉じて上書きします。")
        for h in root_logger.handlers[:]:
            h.close()
        root_logger.handlers.clear()

    # コンソールハンドラー
    if console_level is not None:
        console_handler: logging.StreamHandler[TextIO] = logging.StreamHandler()
        console_handler.setLevel(console_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # ファイルハンドラー
    if file_level is not None:
        file_path = Path(file_name)
        ts: str = datetime.now(tz=_JST).strftime("%Y%m%d%H%M%S")
        stamped: Path = file_path.parent / f"{ts}_{file_path.name}"
        stamped.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(stamped, encoding="utf-8")
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # root logger のレベルは全ハンドラーレベルの最小値に設定する。
    # setLevel() が str→int 変換を行い、.level で int を読み出して比較する。
    if root_logger.handlers:
        root_logger.setLevel(min(h.level for h in root_logger.handlers))
    else:
        root_logger.setLevel(logging.WARNING)
