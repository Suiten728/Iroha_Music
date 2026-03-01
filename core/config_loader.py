"""
core/config_loader.py — 環境変数・設定読み込み
"""

import os


class Config:
    PREFIX: str = os.getenv("BOT_PREFIX", "!")
    YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "")
    FFMPEG_PATH: str = os.getenv("FFMPEG_PATH", "ffmpeg")
    MAX_QUEUE_SIZE: int = int(os.getenv("MAX_QUEUE_SIZE", "200"))
    DEFAULT_VOLUME: float = float(os.getenv("DEFAULT_VOLUME", "0.8"))
    AUTO_LEAVE_SEC: int = int(os.getenv("AUTO_LEAVE_SEC", "300"))
    SENSITIVE_KEYWORDS_SEXUAL: list[str] = [
        "explicit", "nsfw", "adult", "18+", "erotic", "lewd",
    ]
    SENSITIVE_KEYWORDS_VIOLENCE: list[str] = [
        "gore", "brutal", "killing", "murder", "slaughter", "torture",
    ]
    SENSITIVE_KEYWORDS_DEPRESSION: list[str] = [
        "suicide", "self-harm", "cut myself", "want to die",
        "depressed", "hopeless", "end my life",
    ]
