"""
core/logger.py — ロギング設定
"""

import logging
import sys
from pathlib import Path


def setup_logger() -> None:
    Path("logs").mkdir(exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger("iroha")
    root.setLevel(logging.DEBUG)

    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # File
    fh = logging.FileHandler("logs/iroha.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # discord.py のログも出力
    discord_log = logging.getLogger("discord")
    discord_log.setLevel(logging.WARNING)
    discord_log.addHandler(ch)
