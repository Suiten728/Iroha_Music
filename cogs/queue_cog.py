"""
cogs/queue_cog.py — キュー管理補助コマンド
nowplaying は music.py に統合済みのためここには定義しない
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from bot import IrohaBot

log = logging.getLogger("iroha.queue_cog")


async def _ack(ctx: commands.Context) -> None:
    """スラッシュコマンド時に先に defer してタイムアウトを防ぐ"""
    if ctx.interaction and not ctx.interaction.response.is_done():
        await ctx.interaction.response.defer()


class QueueCog(commands.Cog, name="Queue"):
    def __init__(self, bot: "IrohaBot") -> None:
        self.bot = bot

    @commands.hybrid_command(name="remove", aliases=["rm"])
    async def remove(self, ctx: commands.Context, index: int) -> None:
        """キューの指定番号の曲を削除する"""
        await _ack(ctx)
        state = self.bot.guild_manager.get(ctx.guild.id)
        if index < 1 or index > len(state.queue):
            await ctx.send(f"❌ 有効な番号を指定してください (1〜{len(state.queue)})")
            return
        removed = state.queue.pop(index - 1)
        await ctx.send(f"🗑 **{removed['title']}** をキューから削除しました。")

    @commands.hybrid_command(name="move")
    async def move(self, ctx: commands.Context, from_idx: int, to_idx: int) -> None:
        """キューの曲を指定位置に移動する"""
        await _ack(ctx)
        state = self.bot.guild_manager.get(ctx.guild.id)
        q = state.queue
        if not (1 <= from_idx <= len(q)) or not (1 <= to_idx <= len(q)):
            await ctx.send("❌ 有効な番号を指定してください。")
            return
        track = q.pop(from_idx - 1)
        q.insert(to_idx - 1, track)
        await ctx.send(f"✅ **{track['title']}** を {from_idx}番 → {to_idx}番 に移動しました。")

    @commands.hybrid_command(name="clearqueue", aliases=["cq"])
    async def clear_queue(self, ctx: commands.Context) -> None:
        """キューを全クリアする"""
        await _ack(ctx)
        state = self.bot.guild_manager.get(ctx.guild.id)
        count = len(state.queue)
        state.queue.clear()
        await ctx.send(f"🗑 キューをクリアしました。({count}曲)")


async def setup(bot: "IrohaBot") -> None:
    await bot.add_cog(QueueCog(bot))
