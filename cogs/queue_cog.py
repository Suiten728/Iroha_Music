"""
cogs/queue_cog.py — キュー管理補助 / AI診断からのキュー生成
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from utils.audio_engine import YTDLSource

if TYPE_CHECKING:
    from bot import IrohaBot

log = logging.getLogger("iroha.queue_cog")


class QueueCog(commands.Cog, name="Queue"):
    def __init__(self, bot: "IrohaBot") -> None:
        self.bot = bot

    @commands.command(name="remove", aliases=["rm"])
    async def remove(self, ctx: commands.Context, index: int) -> None:
        """キューの指定番号の曲を削除する"""
        state = self.bot.guild_manager.get(ctx.guild.id)
        if index < 1 or index > len(state.queue):
            await ctx.send(f"❌ 有効な番号を指定してください (1〜{len(state.queue)})")
            return
        removed = state.queue.pop(index - 1)
        await ctx.send(f"🗑 **{removed['title']}** をキューから削除しました。")

    @commands.command(name="move")
    async def move(self, ctx: commands.Context, from_idx: int, to_idx: int) -> None:
        """キューの曲を指定位置に移動する"""
        state = self.bot.guild_manager.get(ctx.guild.id)
        q = state.queue
        if not (1 <= from_idx <= len(q)) or not (1 <= to_idx <= len(q)):
            await ctx.send("❌ 有効な番号を指定してください。")
            return
        track = q.pop(from_idx - 1)
        q.insert(to_idx - 1, track)
        await ctx.send(f"✅ **{track['title']}** を {from_idx}番 → {to_idx}番 に移動しました。")

    @commands.command(name="clearqueue", aliases=["cq"])
    async def clear_queue(self, ctx: commands.Context) -> None:
        """キューを全クリアする"""
        state = self.bot.guild_manager.get(ctx.guild.id)
        count = len(state.queue)
        state.queue.clear()
        await ctx.send(f"🗑 キューをクリアしました。({count}曲)")

    @commands.command(name="nowplaying", aliases=["np"])
    async def nowplaying(self, ctx: commands.Context) -> None:
        """現在再生中の曲を表示する"""
        state = self.bot.guild_manager.get(ctx.guild.id)
        if not state.current:
            await ctx.send("❌ 現在再生中の曲はありません。")
            return

        track = state.current
        dur = YTDLSource.format_duration(track.get("duration", 0))
        comps = [
            {
                "type": 17,
                "accent_color": 0x5865F2,
                "components": [
                    {
                        "type": 10,
                        "content": (
                            f"## 🎵 Now Playing\n"
                            f"**{track['title']}**\n\n"
                            f"⏱️ {dur}　🔊 {int(state.volume * 100)}%\n"
                            f"リクエスト: <@{track.get('requester_id', 0)}>"
                        ),
                    },
                    {"type": 14, "spacing": 1},
                    {
                        "type": 9,
                        "components": [{"type": 10, "content": f"📋 キュー残り: {len(state.queue)}曲"}],
                        "accessory": {
                            "type": 2, "style": 5,
                            "label": "YouTube",
                            "url": track.get("webpage_url", "https://youtube.com"),
                        },
                    },
                ],
            }
        ]
        await self.bot.http.request(
            discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=ctx.channel.id),
            json={"flags": 1 << 15, "components": comps},
        )


async def setup(bot: "IrohaBot") -> None:
    await bot.add_cog(QueueCog(bot))
