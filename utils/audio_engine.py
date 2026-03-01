"""
utils/audio_engine.py — yt-dlp ラッパー & FFmpeg フィルターチェーン構築
"""

from __future__ import annotations

import asyncio
import logging
import re
from functools import partial
from typing import Any

import discord
import yt_dlp

log = logging.getLogger("iroha.audio_engine")

YTDL_OPTIONS: dict = {
    "format": "bestaudio/best",
    "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": False,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "postprocessors": [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "opus",
        "preferredquality": "192",
    }],
}

BASE_FFMPEG_OPTIONS: dict = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


# ─── EQ プリセット定義 ──────────────────────────────────────────────
PRESETS: dict[str, dict] = {
    "flat": {},
    "bass_boost": {
        "description": "🔊 Bass Boost — 低域ブースト",
        "equalizer": [
            {"band": 0, "gain": 0.3},
            {"band": 1, "gain": 0.25},
            {"band": 2, "gain": 0.15},
        ],
        "bass_boost": 6,
    },
    "vocal_clear": {
        "description": "🎤 Vocal Clear — ボーカル強調",
        "equalizer": [
            {"band": 5, "gain": 0.2},
            {"band": 6, "gain": 0.25},
            {"band": 7, "gain": 0.2},
        ],
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
        "equalizer": [
            {"band": 0, "gain": -0.2},
            {"band": 1, "gain": -0.1},
            {"band": 8, "gain": 0.1},
            {"band": 9, "gain": 0.15},
        ],
    },
}


def build_ffmpeg_filter(
    volume: float = 1.0,
    bass_boost: int = 0,
    surround: bool = False,
    reverb_level: float = 0.0,
    eq_bands: dict | None = None,
) -> str:
    """
    FFmpeg af フィルターチェーンを構築して文字列で返す。
    """
    filters: list[str] = []

    # ボリューム
    filters.append(f"volume={volume:.2f}")

    # イコライザー（EQ bands: {frequency_hz: gain_db}）
    if eq_bands:
        for freq, gain in eq_bands.items():
            filters.append(f"equalizer=f={freq}:width_type=o:width=2:g={gain}")

    # Bass Boost (低域ブースト)
    if bass_boost > 0:
        filters.append(
            f"bass=g={bass_boost}:f=110:width_type=o:width=0.7"
        )

    # 立体音響（ステレオワイド）
    if surround:
        filters.append("extrastereo=m=2.5,aecho=0.8:0.88:40:0.4")

    # 軽度リバーブ
    if reverb_level > 0:
        delay_ms = int(reverb_level * 200)
        filters.append(
            f"aecho=0.8:0.6:{delay_ms}:{reverb_level:.2f}"
        )

    # クリッピング防止
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
    options = f"-vn -af '{af_chain}'"
    return discord.FFmpegPCMAudio(
        stream_url,
        before_options=BASE_FFMPEG_OPTIONS["before_options"],
        options=options,
    )


class YTDLSource:
    """yt-dlp を使って音楽情報を取得するクラス"""

    _ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

    @classmethod
    async def search(cls, query: str, *, loop: asyncio.AbstractEventLoop | None = None) -> list[dict]:
        """クエリで検索して情報リストを返す（最大5件）"""
        loop = loop or asyncio.get_event_loop()
        search_query = f"ytsearch5:{query}" if not cls._is_url(query) else query
        data = await loop.run_in_executor(
            None,
            partial(cls._ytdl.extract_info, search_query, download=False),
        )
        if data is None:
            return []
        entries = data.get("entries", [data])
        return [cls._parse_entry(e) for e in entries if e]

    @classmethod
    async def fetch_playlist(cls, url: str, *, loop: asyncio.AbstractEventLoop | None = None) -> list[dict]:
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None,
            partial(cls._ytdl.extract_info, url, download=False),
        )
        if data is None:
            return []
        entries = data.get("entries", [data])
        return [cls._parse_entry(e) for e in entries if e]

    @classmethod
    def _parse_entry(cls, entry: dict) -> dict:
        return {
            "title": entry.get("title", "Unknown"),
            "url": entry.get("url") or entry.get("webpage_url", ""),
            "webpage_url": entry.get("webpage_url", ""),
            "duration": entry.get("duration", 0),
            "thumbnail": entry.get("thumbnail", ""),
            "uploader": entry.get("uploader", "Unknown"),
            "id": entry.get("id", ""),
        }

    @staticmethod
    def _is_url(text: str) -> bool:
        return bool(re.match(r"https?://", text))

    @staticmethod
    def format_duration(seconds: int) -> str:
        if not seconds:
            return "不明"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
