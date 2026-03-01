"""
cogs/statistics.py — 音楽利用統計・ランキング表示
月間ランキング / ユーザー別統計 / 活動時間帯分析
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from bot import IrohaBot

log = logging.getLogger("iroha.statistics")


def _stats_components(
    monthly_top: list[dict],
    user_top: list[dict],
    time_analysis: list[dict],
    guild_name: str,
) -> list[dict]:
    # 月間ランキング
    rank_lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(monthly_top[:10]):
        medal = medals[i] if i < 3 else f"`{i+1:2d}.`"
        rank_lines.append(f"{medal} **{row['title'][:40]}** ({row['cnt']}回)")
    rank_text = "\n".join(rank_lines) if rank_lines else "データなし"

    # ユーザーランキング
    user_lines = []
    for i, row in enumerate(user_top[:5]):
        medal = medals[i] if i < 3 else f"`{i+1}.`"
        user_lines.append(f"{medal} <@{row['user_id']}> — {row['cnt']}曲")
    user_text = "\n".join(user_lines) if user_lines else "データなし"

    # 時間帯分析
    time_lines = []
    for row in time_analysis[:5]:
        bar = "█" * min(int(row["cnt"] / max(1, time_analysis[0]["cnt"]) * 10), 10)
        time_lines.append(f"`{row['hour']:02d}:00` {bar} {row['cnt']}曲")
    time_text = "\n".join(time_lines) if time_lines else "データなし"

    return [
        {
            "type": 17,
            "accent_color": 0xFEE75C,
            "components": [
                {
                    "type": 10,
                    "content": f"## 📊 {guild_name} — 音楽統計",
                },
                {"type": 14, "spacing": 2},
                {
                    "type": 10,
                    "content": f"### 🏆 今月の月間ランキング\n{rank_text}",
                },
                {"type": 14, "spacing": 1},
                {
                    "type": 10,
                    "content": f"### 👑 ユーザー再生数ランキング\n{user_text}",
                },
                {"type": 14, "spacing": 1},
                {
                    "type": 10,
                    "content": f"### 🕐 活動時間帯 TOP5\n{time_text}",
                },
                {"type": 14, "spacing": 2},
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 3,
                            "custom_id": "stats:period_select",
                            "placeholder": "期間を選択",
                            "options": [
                                {"label": "📅 今月", "value": "month"},
                                {"label": "📅 過去7日", "value": "week"},
                                {"label": "📅 全期間", "value": "all"},
                            ],
                        }
                    ],
                },
            ],
        }
    ]


def _user_stats_components(user_id: int, rows: list[dict], total: int) -> list[dict]:
    lines = [f"`{i+1:02d}.` **{r['title'][:45]}** ({r['cnt']}回)" for i, r in enumerate(rows[:10])]
    text = "\n".join(lines) if lines else "まだ再生履歴がありません"
    return [
        {
            "type": 17,
            "accent_color": 0x5865F2,
            "components": [
                {
                    "type": 10,
                    "content": f"## 🎵 <@{user_id}> の再生履歴\n合計 **{total}曲** 再生",
                },
                {"type": 14, "spacing": 1},
                {"type": 10, "content": text},
            ],
        }
    ]


class StatsView(discord.ui.View):
    def __init__(self, cog: "Statistics") -> None:
        super().__init__(timeout=None)
        self._cog = cog

    @discord.ui.select(
        custom_id="stats:period_select",
        options=[
            discord.SelectOption(label="今月", value="month"),
            discord.SelectOption(label="過去7日", value="week"),
            discord.SelectOption(label="全期間", value="all"),
        ],
    )
    async def period_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        period = select.values[0]
        await self._cog._refresh_stats(interaction, period)


class Statistics(commands.Cog):
    def __init__(self, bot: "IrohaBot") -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self.bot.add_view(StatsView(self))

    @commands.command(name="stats", aliases=["ranking"])
    async def stats(self, ctx: commands.Context) -> None:
        """サーバーの音楽統計を表示"""
        guild_id = ctx.guild.id

        monthly_top = await self.bot.db.fetchall(
            """SELECT title, COUNT(*) as cnt FROM music_stats
               WHERE guild_id=? AND played_at >= date('now','start of month')
               GROUP BY title ORDER BY cnt DESC LIMIT 10""",
            (guild_id,),
        )
        user_top = await self.bot.db.fetchall(
            """SELECT user_id, COUNT(*) as cnt FROM music_stats
               WHERE guild_id=? AND played_at >= date('now','start of month')
               GROUP BY user_id ORDER BY cnt DESC LIMIT 5""",
            (guild_id,),
        )
        time_analysis = await self.bot.db.fetchall(
            """SELECT CAST(strftime('%H', played_at) AS INTEGER) as hour, COUNT(*) as cnt
               FROM music_stats WHERE guild_id=?
               GROUP BY hour ORDER BY cnt DESC LIMIT 5""",
            (guild_id,),
        )

        comps = _stats_components(
            [dict(r) for r in monthly_top],
            [dict(r) for r in user_top],
            [dict(r) for r in time_analysis],
            ctx.guild.name,
        )
        await self.bot.http.request(
            discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=ctx.channel.id),
            json={"flags": 1 << 15, "components": comps},
        )

    @commands.command(name="mystats")
    async def mystats(self, ctx: commands.Context) -> None:
        """自分の再生履歴を表示"""
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        rows = await self.bot.db.fetchall(
            """SELECT title, COUNT(*) as cnt FROM music_stats
               WHERE guild_id=? AND user_id=?
               GROUP BY title ORDER BY cnt DESC LIMIT 10""",
            (guild_id, user_id),
        )
        total = (await self.bot.db.fetchone(
            "SELECT COUNT(*) as cnt FROM music_stats WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        ) or {}).get("cnt", 0)
        comps = _user_stats_components(user_id, [dict(r) for r in rows], total)
        await self.bot.http.request(
            discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=ctx.channel.id),
            json={"flags": 1 << 15, "components": comps},
        )

    async def _refresh_stats(self, interaction: discord.Interaction, period: str) -> None:
        guild_id = interaction.guild_id
        date_filter = {
            "month": "AND played_at >= date('now','start of month')",
            "week": "AND played_at >= date('now','-7 days')",
            "all": "",
        }.get(period, "")

        monthly_top = await self.bot.db.fetchall(
            f"""SELECT title, COUNT(*) as cnt FROM music_stats
                WHERE guild_id=? {date_filter}
                GROUP BY title ORDER BY cnt DESC LIMIT 10""",
            (guild_id,),
        )
        user_top = await self.bot.db.fetchall(
            f"""SELECT user_id, COUNT(*) as cnt FROM music_stats
                WHERE guild_id=? {date_filter}
                GROUP BY user_id ORDER BY cnt DESC LIMIT 5""",
            (guild_id,),
        )
        time_analysis = await self.bot.db.fetchall(
            f"""SELECT CAST(strftime('%H', played_at) AS INTEGER) as hour, COUNT(*) as cnt
                FROM music_stats WHERE guild_id=? {date_filter}
                GROUP BY hour ORDER BY cnt DESC LIMIT 5""",
            (guild_id,),
        )
        guild = self.bot.get_guild(guild_id)
        comps = _stats_components(
            [dict(r) for r in monthly_top],
            [dict(r) for r in user_top],
            [dict(r) for r in time_analysis],
            guild.name if guild else "Server",
        )
        await interaction.client.http.request(
            discord.http.Route(
                "PATCH",
                "/channels/{channel_id}/messages/{message_id}",
                channel_id=interaction.channel_id,
                message_id=interaction.message.id,
            ),
            json={"flags": 1 << 15, "components": comps},
        )
        await interaction.response.defer()


async def setup(bot: "IrohaBot") -> None:
    await bot.add_cog(Statistics(bot))
