"""
core/guild_manager.py — Guild単位の状態管理
キュー / プレイヤー / 設定をGuildごとに完全分離する
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord
    from bot import IrohaBot

log = logging.getLogger("iroha.guild_manager")


@dataclass
class GuildState:
    """1 Guildの実行時状態"""
    guild_id: int
    queue: list = field(default_factory=list)       # 再生キュー（dict list）
    current: dict | None = None                     # 現在再生中
    volume: float = 0.8
    loop_mode: str = "none"                         # none / one / all
    shuffle: bool = False
    is_playing: bool = False
    skip_votes: set = field(default_factory=set)
    party_mode: bool = False
    quiz_active: bool = False
    auto_leave_task: asyncio.Task | None = None

    # コマンドを打ったテキストチャンネルID（NowPlaying送信先）
    text_channel_id: int | None = None

    # オーディオ設定
    preset: str = "flat"
    bass_boost: int = 0
    surround: bool = False
    eq_bands: dict = field(default_factory=dict)


class GuildManager:
    def __init__(self, bot: "IrohaBot") -> None:
        self.bot = bot
        self._states: dict[int, GuildState] = {}

    def get(self, guild_id: int) -> GuildState:
        if guild_id not in self._states:
            self._states[guild_id] = GuildState(guild_id=guild_id)
        return self._states[guild_id]

    async def ensure_guild(self, guild_id: int) -> None:
        """DBにguild設定が存在することを保証する"""
        db = self.bot.db
        existing = await db.fetchone(
            "SELECT guild_id FROM guild_settings WHERE guild_id = ?", (guild_id,)
        )
        if not existing:
            await db.execute(
                "INSERT OR IGNORE INTO guild_settings(guild_id) VALUES(?)", (guild_id,)
            )
            await db.execute(
                "INSERT OR IGNORE INTO audio_settings(guild_id) VALUES(?)", (guild_id,)
            )
            await db.commit()
            log.info(f"Initialized settings for guild {guild_id}")

    async def get_settings(self, guild_id: int) -> dict:
        row = await self.bot.db.fetchone(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        )
        if row is None:
            await self.ensure_guild(guild_id)
            row = await self.bot.db.fetchone(
                "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
            )
        return dict(row)

    async def get_audio_settings(self, guild_id: int) -> dict:
        row = await self.bot.db.fetchone(
            "SELECT * FROM audio_settings WHERE guild_id = ?", (guild_id,)
        )
        if row is None:
            await self.ensure_guild(guild_id)
            row = await self.bot.db.fetchone(
                "SELECT * FROM audio_settings WHERE guild_id = ?", (guild_id,)
            )
        return dict(row)

    def remove(self, guild_id: int) -> None:
        self._states.pop(guild_id, None)