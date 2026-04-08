# Copyright (c) 2026 U
"""sda.log の動作確認サンプル。"""

import logging

import sda.log

logger: logging.Logger = logging.getLogger(__name__)


def run_console_only() -> None:
    """シナリオ1: コンソールのみに出力する。"""
    sda.log.setup(console_level="DEBUG")

    logger.debug("シナリオ1: デバッグメッセージ")
    logger.info("シナリオ1: 情報メッセージ")
    logger.warning("シナリオ1: 警告メッセージ")
    logger.error("シナリオ1: エラーメッセージ")


def run_console_filtered() -> None:
    """シナリオ2: コンソールに WARNING 以上のみ表示する。"""
    sda.log.setup(console_level="WARNING")

    logger.debug("シナリオ2: デバッグ (コンソールには出ない)")
    logger.info("シナリオ2: 情報 (コンソールには出ない)")
    logger.warning("シナリオ2: 警告 (コンソールに出る)")
    logger.error("シナリオ2: エラー (コンソールに出る)")


def run_file_only(output_dir: str = "output/logs") -> None:
    """シナリオ3: ファイルのみに出力する。

    Parameters
    ----------
    output_dir : str
        ログファイルの出力ディレクトリ。

    """
    sda.log.setup(
        console_level=None,
        file_level="DEBUG",
        file_name=f"{output_dir}/app.log",
    )

    logger.debug("シナリオ3: デバッグメッセージ")
    logger.info("シナリオ3: 情報メッセージ")
    logger.warning("シナリオ3: 警告メッセージ")

    handler: logging.Handler = logging.getLogger().handlers[0]
    if isinstance(handler, logging.FileHandler):
        print(f"ログファイル: {handler.baseFilename}")


def run_console_and_file(output_dir: str = "output/logs") -> None:
    """シナリオ4: コンソールとファイルに同時出力する。

    コンソールは INFO 以上、ファイルは DEBUG 以上を記録する。

    Parameters
    ----------
    output_dir : str
        ログファイルの出力ディレクトリ。

    """
    sda.log.setup(
        console_level="INFO",
        file_level="DEBUG",
        file_name=f"{output_dir}/app.log",
    )

    logger.debug("シナリオ4: デバッグ (ファイルのみ)")
    logger.info("シナリオ4: 情報 (コンソール + ファイル)")
    logger.warning("シナリオ4: 警告 (コンソール + ファイル)")

    handler: logging.Handler = logging.getLogger().handlers[-1]
    if isinstance(handler, logging.FileHandler):
        print(f"ログファイル: {handler.baseFilename}")


def run_fmt_presets() -> None:
    """シナリオ5: フォーマットプリセットの比較。"""
    for fmt in ("default", "simple", "detailed"):
        sda.log.setup(fmt=fmt, console_level="INFO", force=True)
        print(f"--- fmt={fmt!r} ---")
        logger.info("メッセージ")
        print()


def run_force() -> None:
    """シナリオ6: force パラメータの動作確認。

    force=False (デフォルト): すでに設定済みの場合は WARNING を出してスキップ。
    force=True             : 既存ハンドラーを閉じて上書き。INFO ログを出力。
    """
    print("--- 1回目: 初期設定 (DEBUG) ---")
    sda.log.setup(console_level="DEBUG")

    print("--- 2回目: force=False (デフォルト) → スキップされる ---")
    sda.log.setup(console_level="INFO")  # WARNING が出てスキップ

    print("--- 3回目: force=True → 上書き (INFO) ---")
    sda.log.setup(console_level="INFO", force=True)  # INFO ログ後に上書き

    logger.debug("DEBUG: force=True 後は出ない (INFO 以上のみ)")
    logger.info("INFO: force=True 後は出る")


if __name__ == "__main__":
    import sys
    from collections.abc import Callable

    scenarios: dict[str, Callable[[], None]] = {
        "console": run_console_only,
        "filtered": run_console_filtered,
        "file": run_file_only,
        "both": run_console_and_file,
        "fmt": run_fmt_presets,
        "force": run_force,
    }

    scenario: str = sys.argv[1] if len(sys.argv) > 1 else "all"

    if scenario == "all":
        for name, fn in scenarios.items():
            print(f"\n=== シナリオ: {name} ===")
            fn()
            # 次のシナリオのために root logger をリセット
            root: logging.Logger = logging.getLogger()
            for h in root.handlers[:]:
                h.close()
            root.handlers.clear()
    elif scenario in scenarios:
        scenarios[scenario]()
    else:
        print(f"使用法: python log_example.py [{'|'.join(scenarios)}|all]")
