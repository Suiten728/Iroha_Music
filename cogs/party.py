"""
cogs/party.py — パーティーモード / 曲当てクイズ / イントロクイズ
DJ交代制 / 曲投票 / 盛り上がりスコア
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from utils.audio_engine import YTDLSource

if TYPE_CHECKING:
    from bot import IrohaBot

log = logging.getLogger("iroha.party")


def _party_panel_components(
    guild_id: int,
    dj_queue: list[int],
    current_dj: int | None,
    hype_score: int,
    is_active: bool,
) -> list[dict]:
    dj_text = f"<@{current_dj}>" if current_dj else "なし"
    waiting = " → ".join(f"<@{uid}>" for uid in dj_queue[:5]) or "なし"
    hype_bar = "🔥" * min(hype_score // 10, 10) + "⬛" * (10 - min(hype_score // 10, 10))

    return [
        {
            "type": 17,
            "accent_color": 0xFF6B6B,
            "components": [
                {
                    "type": 10,
                    "content": (
                        f"## 🎉 パーティーモード {'🟢 ON' if is_active else '🔴 OFF'}\n"
                        f"**現在のDJ:** {dj_text}\n"
                        f"**DJ待ち:** {waiting}\n\n"
                        f"**🔥 盛り上がりスコア:** {hype_score}pt\n"
                        f"{hype_bar}"
                    ),
                },
                {"type": 14, "spacing": 2},
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 2,
                            "style": 1 if not is_active else 4,
                            "label": "🎉 パーティー開始" if not is_active else "🛑 パーティー終了",
                            "custom_id": f"party:toggle:{guild_id}",
                        },
                        {"type": 2, "style": 2, "label": "🎤 DJに立候補", "custom_id": f"party:join_dj:{guild_id}"},
                        {"type": 2, "style": 2, "label": "⏭ DJ交代", "custom_id": f"party:next_dj:{guild_id}"},
                    ],
                },
                {
                    "type": 1,
                    "components": [
                        {"type": 2, "style": 1, "label": "🗳 曲を投票", "custom_id": f"party:vote:{guild_id}"},
                        {"type": 2, "style": 2, "label": "🔥 盛り上がり！", "custom_id": f"party:hype:{guild_id}"},
                    ],
                },
            ],
        }
    ]


def _quiz_components(title: str, options: list[str], correct_idx: int, token: str, guild_id: int) -> list[dict]:
    buttons = [
        {
            "type": 2,
            "style": 1,
            "label": opt[:80],
            "custom_id": f"quiz:answer:{guild_id}:{token}:{i}:{correct_idx}",
        }
        for i, opt in enumerate(options)
    ]
    return [
        {
            "type": 17,
            "accent_color": 0xFEE75C,
            "components": [
                {"type": 10, "content": "## 🎵 曲当てクイズ\n**この曲は何でしょう？** イントロを聴いて答えてください！"},
                {"type": 14, "spacing": 2},
                {"type": 1, "components": buttons[:4]},
            ],
        }
    ]


class PartyView(discord.ui.View):
    def __init__(self, cog: "Party") -> None:
        super().__init__(timeout=None)
        self._cog = cog

    @discord.ui.button(custom_id="party:toggle", label="🎉 パーティー", style=discord.ButtonStyle.primary)
    async def toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        parts = interaction.data["custom_id"].split(":")
        guild_id = int(parts[2])
        await self._cog._toggle_party(interaction, guild_id)

    @discord.ui.button(custom_id="party:join_dj", label="🎤 DJ立候補", style=discord.ButtonStyle.secondary)
    async def join_dj(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        parts = interaction.data["custom_id"].split(":")
        guild_id = int(parts[2])
        await self._cog._join_dj(interaction, guild_id)

    @discord.ui.button(custom_id="party:next_dj", label="⏭ DJ交代", style=discord.ButtonStyle.secondary)
    async def next_dj(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        parts = interaction.data["custom_id"].split(":")
        guild_id = int(parts[2])
        await self._cog._next_dj(interaction, guild_id)

    @discord.ui.button(custom_id="party:hype", label="🔥 盛り上がり", style=discord.ButtonStyle.secondary)
    async def hype_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        parts = interaction.data["custom_id"].split(":")
        guild_id = int(parts[2])
        await self._cog._add_hype(interaction, guild_id)

    @discord.ui.button(custom_id="quiz:answer", label="回答", style=discord.ButtonStyle.primary)
    async def quiz_answer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        parts = interaction.data["custom_id"].split(":")
        # quiz:answer:guild_id:token:choice_idx:correct_idx
        if len(parts) < 6:
            return
        guild_id = int(parts[2])
        choice = int(parts[4])
        correct = int(parts[5])
        await self._cog._quiz_answer(interaction, guild_id, choice, correct)


class Party(commands.Cog):
    def __init__(self, bot: "IrohaBot") -> None:
        self.bot = bot
        self._party_states: dict[int, dict] = {}

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self.bot.add_view(PartyView(self))

    def _get_state(self, guild_id: int) -> dict:
        if guild_id not in self._party_states:
            self._party_states[guild_id] = {
                "active": False,
                "dj_queue": [],
                "current_dj": None,
                "hype_score": 0,
                "hype_voters": set(),
            }
        return self._party_states[guild_id]

    @commands.command(name="party")
    async def party(self, ctx: commands.Context) -> None:
        """パーティーモードパネルを表示する"""
        guild_id = ctx.guild.id
        state = self._get_state(guild_id)
        comps = _party_panel_components(
            guild_id,
            state["dj_queue"],
            state["current_dj"],
            state["hype_score"],
            state["active"],
        )
        await self.bot.http.request(
            discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=ctx.channel.id),
            json={"flags": 1 << 15, "components": comps},
        )

    @commands.command(name="quiz")
    async def quiz(self, ctx: commands.Context) -> None:
        """曲当てクイズを開始する"""
        guild_id = ctx.guild.id
        music_cog = self.bot.get_cog("Music")
        state = self.bot.guild_manager.get(guild_id)

        if not state.current and not state.queue:
            await ctx.send("❌ キューに曲がありません。先に曲を追加してください。")
            return

        # 正解曲
        correct_track = state.current or state.queue[0]
        correct_title = correct_track["title"]

        # ダミー選択肢（キューから）
        all_titles = [t["title"] for t in state.queue if t["title"] != correct_title]
        # ダミーが足りない場合はランダム生成
        dummy_pool = ["Mystery Song A", "Unknown Track B", "Hidden Gem C", "Secret Hit D"]
        while len(all_titles) < 3:
            all_titles.append(random.choice(dummy_pool))
            dummy_pool = [d for d in dummy_pool if d not in all_titles]

        options = random.sample(all_titles[:5], 3) + [correct_title]
        random.shuffle(options)
        correct_idx = options.index(correct_title)

        import uuid
        token = uuid.uuid4().hex[:8]
        comps = _quiz_components(correct_title, options, correct_idx, token, guild_id)
        await self.bot.http.request(
            discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=ctx.channel.id),
            json={"flags": 1 << 15, "components": comps},
        )

    async def _toggle_party(self, interaction: discord.Interaction, guild_id: int) -> None:
        state = self._get_state(guild_id)
        state["active"] = not state["active"]
        if not state["active"]:
            state["hype_voters"].clear()
        comps = _party_panel_components(
            guild_id, state["dj_queue"], state["current_dj"],
            state["hype_score"], state["active"],
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

    async def _join_dj(self, interaction: discord.Interaction, guild_id: int) -> None:
        state = self._get_state(guild_id)
        user_id = interaction.user.id
        if user_id not in state["dj_queue"]:
            state["dj_queue"].append(user_id)
            if state["current_dj"] is None:
                state["current_dj"] = state["dj_queue"].pop(0)
        comps = _party_panel_components(
            guild_id, state["dj_queue"], state["current_dj"],
            state["hype_score"], state["active"],
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

    async def _next_dj(self, interaction: discord.Interaction, guild_id: int) -> None:
        state = self._get_state(guild_id)
        if state["dj_queue"]:
            state["current_dj"] = state["dj_queue"].pop(0)
        else:
            state["current_dj"] = None
        comps = _party_panel_components(
            guild_id, state["dj_queue"], state["current_dj"],
            state["hype_score"], state["active"],
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

    async def _add_hype(self, interaction: discord.Interaction, guild_id: int) -> None:
        state = self._get_state(guild_id)
        user_id = interaction.user.id
        if user_id not in state["hype_voters"]:
            state["hype_voters"].add(user_id)
            state["hype_score"] += 5
        comps = _party_panel_components(
            guild_id, state["dj_queue"], state["current_dj"],
            state["hype_score"], state["active"],
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

    async def _quiz_answer(
        self, interaction: discord.Interaction, guild_id: int, choice: int, correct: int
    ) -> None:
        is_correct = choice == correct
        result_text = "🎉 **正解！** おめでとうございます！" if is_correct else "❌ **不正解...** また次回！"
        comps = [
            {
                "type": 17,
                "accent_color": 0x57F287 if is_correct else 0xED4245,
                "components": [
                    {
                        "type": 10,
                        "content": f"## 🎵 クイズ結果\n{result_text}\n\n<@{interaction.user.id}> が回答しました。",
                    }
                ],
            }
        ]
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
    await bot.add_cog(Party(bot))
