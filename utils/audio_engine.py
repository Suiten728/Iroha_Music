"""
utils/audio_engine.py — yt-dlp ラッパー & FFmpeg フィルターチェーン構築
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from functools import partial

import discord
import yt_dlp

log = logging.getLogger("iroha.audio_engine")

# ─── ffmpeg パス解決 ──────────────────────────────────────────────────
_FFMPEG_CANDIDATES = [
    # 環境変数
    os.environ.get("FFMPEG_PATH", ""),
    # PATH上のffmpeg
    shutil.which("ffmpeg") or "",
    # よくある固定パス（Linux）
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    # よくある固定パス（macOS Homebrew）
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/Cellar/ffmpeg/bin/ffmpeg",
    # Windows
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
]

def _resolve_ffmpeg() -> str:
    for candidate in _FFMPEG_CANDIDATES:
        if candidate and os.path.isfile(candidate):
            log.info(f"ffmpeg found: {candidate}")
            return candidate
    # 最後の手段: PATH上の "ffmpeg" をそのまま渡す（discord.py にエラーを任せる）
    log.warning("ffmpeg が自動検出できませんでした。PATH上にffmpegがあることを確認してください。")
    return "ffmpeg"

FFMPEG_EXEC: str = _resolve_ffmpeg()

# ─── yt-dlp 設定（ストリーミング専用・postprocessor なし）────────────
YTDL_OPTIONS: dict = {
    "format": "bestaudio/best",
    "restrictfilenames": True,
    "noplaylist": False,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    # postprocessors は削除 — ダウンロードせずストリームURLを直接使うため
}

YTDL_OPTIONS_SEARCH: dict = {**YTDL_OPTIONS, "noplaylist": True}

BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"


# ─── EQ プリセット定義 ──────────────────────────────────────────────
PRESETS: dict[str, dict] = {
    "flat": {},
    "bass_boost": {
        "description": "🔊 Bass Boost — 低域ブースト",
        "bass_boost": 6,
    },
    "vocal_clear": {
        "description": "🎤 Vocal Clear — ボーカル強調",
        "eq_bands": {"2000": 4, "3000": 5, "4000": 4},
    },
    "surround_3d": {
        "description": "🌐 3D Surround — 立体音響",
        "surround": True,
    },
    "live_hall": {
        "description": "🏟️ Live Hall — ライブホール",
        "reverb": 0.4,
        "surround": True,
    },
    "night_mode": {
        "description": "🌙 Night Mode — 低音抑制・高音強調",
        "eq_bands": {"60": -4, "120": -2, "8000": 2, "12000": 3},
    },
}


def build_ffmpeg_filter(
    volume: float = 1.0,
    bass_boost: int = 0,
    surround: bool = False,
    reverb_level: float = 0.0,
    eq_bands: dict | None = None,
) -> str:
    """FFmpeg af フィルターチェーンを構築して文字列で返す。"""
    filters: list[str] = []

    filters.append(f"volume={volume:.2f}")

    if eq_bands:
        for freq, gain in eq_bands.items():
            filters.append(f"equalizer=f={freq}:width_type=o:width=2:g={gain}")

    if bass_boost > 0:
        filters.append(f"bass=g={bass_boost}:f=110:width_type=o:width=0.7")

    if surround:
        filters.append("extrastereo=m=2.5")
        filters.append("aecho=0.8:0.88:40:0.4")

    if reverb_level > 0:
        delay_ms = int(reverb_level * 200)
        filters.append(f"aecho=0.8:0.6:{delay_ms}:{reverb_level:.2f}")

    filters.append("alimiter=limit=0.99:level=1")

    return ",".join(filters)


def make_ffmpeg_source(
    stream_url: str,
    *,
    volume: float = 1.0,
    bass_boost: int = 0,
    surround: bool = False,
    reverb_level: float = 0.0,
    eq_bands: dict | None = None,
) -> discord.FFmpegPCMAudio:
    af_chain = build_ffmpeg_filter(
        volume=volume,
        bass_boost=bass_boost,
        surround=surround,
        reverb_level=reverb_level,
        eq_bands=eq_bands,
    )
    log.debug(f"FFmpeg executable: {FFMPEG_EXEC}")
    log.debug(f"FFmpeg af chain: {af_chain}")

    return discord.FFmpegPCMAudio(
        stream_url,
        executable=FFMPEG_EXEC,
        before_options=BEFORE_OPTIONS,
        options=f"-vn -af {af_chain}",
    )


class YTDLSource:
    """yt-dlp を使って音楽情報を取得するクラス"""

    _ytdl_search   = yt_dlp.YoutubeDL(YTDL_OPTIONS_SEARCH)
    _ytdl_playlist = yt_dlp.YoutubeDL(YTDL_OPTIONS)

    @classmethod
    async def search(
        cls, query: str, *, loop: asyncio.AbstractEventLoop | None = None
    ) -> list[dict]:
        loop = loop or asyncio.get_event_loop()
        search_query = f"ytsearch5:{query}" if not cls._is_url(query) else query
        try:
            data = await loop.run_in_executor(
                None,
                partial(cls._ytdl_search.extract_info, search_query, download=False),
            )
        except Exception as e:
            log.error(f"yt-dlp search error: {e}")
            return []
        if data is None:
            return []
        entries = data.get("entries", [data])
        return [cls._parse_entry(e) for e in entries if e]

    @classmethod
    async def fetch_playlist(
        cls, url: str, *, loop: asyncio.AbstractEventLoop | None = None
    ) -> list[dict]:
        loop = loop or asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(
                None,
                partial(cls._ytdl_playlist.extract_info, url, download=False),
            )
        except Exception as e:
            log.error(f"yt-dlp playlist error: {e}")
            return []
        if data is None:
            return []
        entries = data.get("entries", [data])
        return [cls._parse_entry(e) for e in entries if e]

    @classmethod
    async def get_stream_url(
        cls, webpage_url: str, *, loop: asyncio.AbstractEventLoop | None = None
    ) -> str | None:
        """
        再生直前に webpage_url から最新のストリームURLを取得する。
        ストリームURLは期限付きのためキューには保存せず、再生直前に毎回呼ぶ。
        """
        loop = loop or asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(
                None,
                partial(cls._ytdl_search.extract_info, webpage_url, download=False),
            )
        except Exception as e:
            log.error(f"yt-dlp stream URL fetch error: {e}")
            return None
        if data is None:
            return None
        if "entries" in data:
            data = data["entries"][0]
        url = data.get("url")
        log.debug(f"Stream URL fetched for {webpage_url}: {str(url)[:80]}...")
        return url

    @classmethod
    def _parse_entry(cls, entry: dict) -> dict:
        """yt-dlp エントリからキュー用 dict を生成する。stream_url は保存しない"""
        return {
            "title":       entry.get("title", "Unknown"),
            "webpage_url": entry.get("webpage_url") or entry.get("url", ""),
            "duration":    entry.get("duration", 0),
            "thumbnail":   entry.get("thumbnail", ""),
            "uploader":    entry.get("uploader", "Unknown"),
            "id":          entry.get("id", ""),
        }

    @staticmethod
    def _is_url(text: str) -> bool:
        return bool(re.match(r"https?://", text))

    @staticmethod
    def format_duration(seconds: int | None) -> str:
        if not seconds:
            return "不明"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"