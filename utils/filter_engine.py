"""
utils/filter_engine.py — センシティブ楽曲検知エンジン
タイトル・アーティスト名・タグ情報をスキャンして警告フラグを返す
"""

from __future__ import annotations

import re
from core.config_loader import Config

FLAG_SEXUAL = "sexual"
FLAG_VIOLENCE = "violence"
FLAG_DEPRESSION = "depression"

# パターン（大文字小文字無視）
_PATTERNS: dict[str, list[re.Pattern]] = {
    FLAG_SEXUAL: [re.compile(kw, re.IGNORECASE) for kw in Config.SENSITIVE_KEYWORDS_SEXUAL],
    FLAG_VIOLENCE: [re.compile(kw, re.IGNORECASE) for kw in Config.SENSITIVE_KEYWORDS_VIOLENCE],
    FLAG_DEPRESSION: [re.compile(kw, re.IGNORECASE) for kw in Config.SENSITIVE_KEYWORDS_DEPRESSION],
}

FLAG_LABELS: dict[str, str] = {
    FLAG_SEXUAL: "🔞 性的表現",
    FLAG_VIOLENCE: "⚠️ 暴力的表現",
    FLAG_DEPRESSION: "💙 自傷・鬱的表現",
}

FLAG_COLORS: dict[str, int] = {
    FLAG_SEXUAL: 0xFF6B6B,
    FLAG_VIOLENCE: 0xFF8C00,
    FLAG_DEPRESSION: 0x6495ED,
}


def scan_track(track: dict) -> list[str]:
    """
    楽曲情報をスキャンして検知フラグのリストを返す。
    track: {title, uploader, tags?, description?}
    """
    text = " ".join([
        track.get("title", ""),
        track.get("uploader", ""),
        track.get("description", ""),
        " ".join(track.get("tags", [])) if isinstance(track.get("tags"), list) else "",
    ]).lower()

    flags: list[str] = []
    for flag, patterns in _PATTERNS.items():
        for pat in patterns:
            if pat.search(text):
                flags.append(flag)
                break

    return flags


def format_flag_summary(flags: list[str]) -> str:
    """フラグの日本語サマリーを返す"""
    if not flags:
        return "（フラグなし）"
    return "　".join(FLAG_LABELS.get(f, f) for f in flags)
