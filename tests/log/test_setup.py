# Copyright (c) 2026 U
"""sda.log.setup() のテスト。"""

import logging
import re
from collections.abc import Generator
from pathlib import Path

import pytest

import sda.log

_NUM_HANDLERS_TWO = 2


@pytest.fixture(autouse=True)
def reset_root_logger() -> Generator[None]:
    """各テスト後に root logger をリセットする。"""
    yield
    root_logger: logging.Logger = logging.getLogger()
    for h in root_logger.handlers[:]:
        h.close()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.WARNING)


class TestSetupConsole:
    """console_level パラメータのテスト。"""

    @staticmethod
    def test_console_handler_added() -> None:
        """Console_level 指定時に StreamHandler が追加される。"""
        sda.log.setup(console_level="INFO", file_level=None)
        root_logger: logging.Logger = logging.getLogger()
        assert len(root_logger.handlers) == 1
        assert isinstance(root_logger.handlers[0], logging.StreamHandler)

    @staticmethod
    def test_console_handler_level() -> None:
        """Console_level がハンドラーに反映される。"""
        sda.log.setup(console_level="WARNING", file_level=None)
        assert logging.getLogger().handlers[0].level == logging.WARNING

    @staticmethod
    def test_console_none_adds_no_handler(tmp_path: Path) -> None:
        """Console_level=None のときコンソールハンドラーが追加されない。"""
        sda.log.setup(console_level=None, file_level="INFO", file_name=tmp_path / "app.log")
        # FileHandler は StreamHandler のサブクラス。
        # FileHandler 以外の StreamHandler (=コンソールハンドラー) が
        # 1つでもあれば any=True となり assert エラーになる。
        assert not any(
            isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
            for h in logging.getLogger().handlers
        )


class TestSetupFile:
    """file_level / file_name パラメータのテスト。"""

    @staticmethod
    def test_file_handler_added(tmp_path: Path) -> None:
        """File_level 指定時に FileHandler が追加される。"""
        sda.log.setup(console_level=None, file_level="DEBUG", file_name=tmp_path / "app.log")
        root_logger: logging.Logger = logging.getLogger()
        assert len(root_logger.handlers) == 1
        assert isinstance(root_logger.handlers[0], logging.FileHandler)

    @staticmethod
    def test_file_handler_level(tmp_path: Path) -> None:
        """File_level がハンドラーに反映される。"""
        sda.log.setup(console_level=None, file_level="ERROR", file_name=tmp_path / "app.log")
        handler: logging.Handler = logging.getLogger().handlers[0]
        assert handler.level == logging.ERROR

    @staticmethod
    def test_file_name_has_timestamp_prefix(tmp_path: Path) -> None:
        """生成されるファイル名が YYYYmmddHHMMSS_app.log の形式になる。"""
        sda.log.setup(console_level=None, file_level="DEBUG", file_name=tmp_path / "app.log")
        handler: logging.Handler = logging.getLogger().handlers[0]
        assert isinstance(handler, logging.FileHandler)
        assert re.search(r"\d{14}_app\.log$", handler.baseFilename)

    @staticmethod
    def test_file_parent_dir_created(tmp_path: Path) -> None:
        """存在しない親ディレクトリが自動作成される。"""
        sda.log.setup(console_level=None, file_level="DEBUG", file_name=tmp_path / "a" / "b" / "app.log")
        assert (tmp_path / "a" / "b").is_dir()

    @staticmethod
    def test_file_is_written(tmp_path: Path) -> None:
        """ログメッセージがファイルに書き込まれる。"""
        sda.log.setup(console_level=None, file_level="DEBUG", file_name=tmp_path / "app.log")
        logging.getLogger("test").debug("テストメッセージ")
        handler: logging.Handler = logging.getLogger().handlers[0]
        assert isinstance(handler, logging.FileHandler)
        handler.flush()
        content: str = Path(handler.baseFilename).read_text(encoding="utf-8")
        assert "テストメッセージ" in content

    @staticmethod
    def test_file_none_adds_no_handler() -> None:
        """File_level=None のときファイルハンドラーが追加されない。"""
        sda.log.setup(console_level="INFO", file_level=None)
        assert not any(isinstance(h, logging.FileHandler) for h in logging.getLogger().handlers)

    @staticmethod
    def test_default_file_name_used_when_omitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """File_name 省略時にデフォルトパスが使われる。"""
        monkeypatch.chdir(tmp_path)
        sda.log.setup(console_level=None, file_level="DEBUG")
        handler: logging.Handler = logging.getLogger().handlers[0]
        assert isinstance(handler, logging.FileHandler)
        assert re.search(r"\d{14}_app\.log$", handler.baseFilename)


class TestSetupBothHandlers:
    """console_level と file_level を同時指定するテスト。"""

    @staticmethod
    def test_both_handlers_added(tmp_path: Path) -> None:
        """両方指定時に2つのハンドラーが追加される。"""
        sda.log.setup(console_level="INFO", file_level="DEBUG", file_name=tmp_path / "app.log")
        assert len(logging.getLogger().handlers) == _NUM_HANDLERS_TWO


class TestSetupRootLevel:
    """root logger レベルの自動設定テスト。"""

    @staticmethod
    def test_root_level_is_min_of_handlers(tmp_path: Path) -> None:
        """Root logger レベルが全ハンドラーの最小値になる。"""
        sda.log.setup(console_level="WARNING", file_level="DEBUG", file_name=tmp_path / "app.log")
        assert logging.getLogger().level == logging.DEBUG

    @staticmethod
    def test_root_level_console_only() -> None:
        """Console のみのとき root logger が console_level に合わせる。"""
        sda.log.setup(console_level="ERROR", file_level=None)
        assert logging.getLogger().level == logging.ERROR

    @staticmethod
    def test_root_level_file_only(tmp_path: Path) -> None:
        """File のみのとき root logger が file_level に合わせる。"""
        sda.log.setup(console_level=None, file_level="DEBUG", file_name=tmp_path / "app.log")
        assert logging.getLogger().level == logging.DEBUG


class TestSetupBothNone:
    """console_level と file_level が両方 None のテスト。"""

    @staticmethod
    def test_raises_when_both_none() -> None:
        """両方 None のとき ValueError が発生する。"""
        with pytest.raises(ValueError, match="両方 None"):
            sda.log.setup(console_level=None, file_level=None)


class TestSetupFmt:
    """fmt パラメータのテスト。"""

    @staticmethod
    def test_invalid_fmt_raises() -> None:
        """未定義の fmt を指定すると ValueError が発生する。"""
        with pytest.raises(ValueError, match="fmt"):
            sda.log.setup(fmt="unknown")  # type: ignore[arg-type]

    @staticmethod
    @pytest.mark.parametrize("fmt", ["default", "simple", "detailed"])
    def test_valid_fmt_does_not_raise(fmt: sda.log.FmtName) -> None:
        """有効な fmt プリセットは例外なく設定できる。"""
        sda.log.setup(fmt=fmt, console_level="INFO")


class TestSetupForce:
    """force パラメータのテスト。"""

    @staticmethod
    def test_second_call_without_force_is_ignored() -> None:
        """force=False のとき、2回目の呼び出しは無視される。"""
        sda.log.setup(console_level="DEBUG", file_level=None)
        sda.log.setup(console_level="INFO", file_level=None)  # force=False (デフォルト)
        assert len(logging.getLogger().handlers) == 1
        assert logging.getLogger().handlers[0].level == logging.DEBUG  # 最初の設定が維持される

    @staticmethod
    def test_second_call_without_force_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
        """force=False のとき、スキップされたことを WARNING ログに出力する。"""
        sda.log.setup(console_level="DEBUG", file_level=None)
        with caplog.at_level(logging.WARNING, logger="sda.log"):
            sda.log.setup(console_level="INFO", file_level=None)
        assert "force=True" in caplog.text

    @staticmethod
    def test_second_call_with_force_overwrites() -> None:
        """force=True のとき、既存ハンドラーを閉じて上書きする。"""
        sda.log.setup(console_level="DEBUG", file_level=None)
        sda.log.setup(console_level="INFO", file_level=None, force=True)
        assert len(logging.getLogger().handlers) == 1
        assert logging.getLogger().handlers[0].level == logging.INFO

    @staticmethod
    def test_force_closes_file_handler(tmp_path: Path) -> None:
        """force=True のとき、既存の FileHandler が閉じられる (FD リークなし)。"""
        sda.log.setup(console_level=None, file_level="DEBUG", file_name=tmp_path / "app.log")
        old_handler = logging.getLogger().handlers[0]
        assert isinstance(old_handler, logging.FileHandler)

        sda.log.setup(console_level="INFO", file_level=None, force=True)

        # 旧ハンドラーのストリームが閉じられている
        assert old_handler.stream.closed

    @staticmethod
    def test_force_logs_info_on_overwrite(caplog: pytest.LogCaptureFixture) -> None:
        """force=True のとき、上書きすることを INFO ログに出力する。"""
        sda.log.setup(console_level="DEBUG", file_level=None)
        with caplog.at_level(logging.INFO, logger="sda.log"):
            sda.log.setup(console_level="INFO", file_level=None, force=True)
        assert "force=True" in caplog.text
