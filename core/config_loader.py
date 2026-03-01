"""
core/config_loader.py — 環境変数・設定読み込み
"""

import os
import shutil
import logging

log = logging.getLogger("iroha.config")


class Config:
    PREFIX: str            = os.getenv("BOT_PREFIX", "IM!")
    FFMPEG_PATH: str       = os.getenv("FFMPEG_PATH", "ffmpeg")
    MAX_QUEUE_SIZE: int    = int(os.getenv("MAX_QUEUE_SIZE", "200"))
    DEFAULT_VOLUME: float  = float(os.getenv("DEFAULT_VOLUME", "0.8"))
    AUTO_LEAVE_SEC: int    = int(os.getenv("AUTO_LEAVE_SEC", "300"))

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

    @classmethod
    def check_dependencies(cls) -> None:
        """
        起動時に依存コマンドの存在を確認してログに出す。
        ffmpeg が見つからない場合は明確なエラーを表示する。
        """
        # ffmpeg チェック
        ffmpeg_path = cls.FFMPEG_PATH
        found = None

        # 1. 環境変数に絶対パスが設定されている場合
        if os.path.isfile(ffmpeg_path):
            found = ffmpeg_path
        # 2. PATH から探す
        elif shutil.which(ffmpeg_path):
            found = shutil.which(ffmpeg_path)
        # 3. よくある固定パスを探す
        else:
            candidates = [
                "/usr/bin/ffmpeg",
                "/usr/local/bin/ffmpeg",
                "/opt/homebrew/bin/ffmpeg",
                "/snap/bin/ffmpeg",
            ]
            for c in candidates:
                if os.path.isfile(c):
                    found = c
                    break

        if found:
            print(f"✅ ffmpeg 検出: {found}")
        else:
            print("=" * 60)
            print("❌ ffmpeg が見つかりません！")
            print("   音楽再生には ffmpeg が必須です。")
            print()
            print("   インストール方法:")
            print("   Ubuntu/Debian : sudo apt install ffmpeg")
            print("   macOS         : brew install ffmpeg")
            print("   Windows       : https://ffmpeg.org/download.html")
            print()
            print("   インストール後に .env へパスを設定することも可能です:")
            print("   FFMPEG_PATH=/usr/bin/ffmpeg")
            print("=" * 60)