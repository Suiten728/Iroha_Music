"""
cogs/party.py — パーティーモード / 曲当てクイズ / イントロクイズ
全インタラクションで必ず先に defer() する
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from utils.audio_engine import YTDLSource

if TYPE_CHECKING:
    from bot import IrohaBot

log = logging.getLogger("iroha.party")


async def _ack(ctx: commands.Context) -> None:
    if ctx.interaction and not ctx.interaction.response.is_done():
        await ctx.interaction.response.defer()


async def _post_v2(bot, channel_id: int, components: list[dict]) -> None:
    await bot.http.request(
        discord.http.Route(
            "POST", "/channels/{channel_id}/messages",
            channel_id=channel_id,
        ),
        json={"flags": 1 << 15, "components": components},
    )


async def _edit_v2(bot, channel_id: int, message_id: int, components: list[dict]) -> None:
    await bot.http.request(
        discord.http.Route(
            "PATCH",
            "/channels/{channel_id}/messages/{message_id}",
            channel_id=channel_id,
            message_id=message_id,
        ),
        json={"flags": 1 << 15, "components": components},
    )


# ── Component ビルダー ─────────────────────────────────────────────────

def _party_components(guild_id: int, state: dict) -> list[dict]:
    is_active   = state["active"]
    current_dj  = state["current_dj"]
    dj_queue    = state["dj_queue"]
    hype_score  = state["hype_score"]

    dj_text     = f"<@{current_dj}>" if current_dj else "なし"
    waiting     = " → ".join(f"<@{uid}>" for uid in dj_queue[:5]) or "なし"
    hype_filled = min(hype_score // 10, 10)
    hype_bar    = "🔥" * hype_filled + "⬛" * (10 - hype_filled)

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
                            "style": 4 if is_active else 1,
                            "label": "🛑 パーティー終了" if is_active else "🎉 パーティー開始",
                            "custom_id": f"party:toggle:{guild_id}",
                        },
                        {"type": 2, "style": 2, "label": "🎤 DJに立候補", "custom_id": f"party:join_dj:{guild_id}"},
                        {"type": 2, "style": 2, "label": "⏭ DJ交代",     "custom_id": f"party:next_dj:{guild_id}"},
                    ],
                },
                {
                    "type": 1,
                    "components": [
                        {"type": 2, "style": 1, "label": "🔥 盛り上がり！", "custom_id": f"party:hype:{guild_id}"},
                    ],
                },
            ],
        }
    ]


def _quiz_components(options: list[str], correct_idx: int, token: str, guild_id: int) -> list[dict]:
    buttons = [
        {
            "type": 2,
            "style": 1,
            "label": opt[:80],
            "custom_id": f"quiz:ans:{guild_id}:{token}:{i}:{correct_idx}",
        }
        for i, opt in enumerate(options)
    ]
    return [
        {
            "type": 17,
            "accent_color": 0xFEE75C,
            "components": [
                {
                    "type": 10,
                    "content": "## 🎵 曲当てクイズ\n**この曲は何でしょう？**\n今流れているイントロを聴いて答えてください！",
                },
                {"type": 14, "spacing": 2},
                {"type": 1, "components": buttons[:4]},
            ],
        }
    ]


# ── Persistent View ────────────────────────────────────────────────────

class PartyView(discord.ui.View):
    """パーティーパネル・クイズのインタラクションを受け取る Persistent View"""

    def __init__(self, cog: "Party") -> None:
        super().__init__(timeout=None)
        self._cog = cog

    # ─── 動的 custom_id を on_interaction で一括処理 ────────────────────
    # party:toggle / party:join_dj / party:next_dj / party:hype は
    # guild_id が埋め込まれているため @discord.ui.button では登録不可
    # → on_interaction で prefix マッチして処理する

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type != discord.InteractionType.component:
            return
        custom_id: str = interaction.data.get("custom_id", "")

        # ─ party: 系 ────────────────────────────────────────
        if custom_id.startswith("party:toggle:"):
            await interaction.response.defer()
            guild_id = int(custom_id.split(":")[-1])
            await self._cog._toggle_party(interaction, guild_id)

        elif custom_id.startswith("party:join_dj:"):
            await interaction.response.defer()
            guild_id = int(custom_id.split(":")[-1])
            await self._cog._join_dj(interaction, guild_id)

        elif custom_id.startswith("party:next_dj:"):
            await interaction.response.defer()
            guild_id = int(custom_id.split(":")[-1])
            await self._cog._next_dj(interaction, guild_id)

        elif custom_id.startswith("party:hype:"):
            await interaction.response.defer()
            guild_id = int(custom_id.split(":")[-1])
            await self._cog._add_hype(interaction, guild_id)

        # ─ quiz:ans: 系 ──────────────────────────────────────
        # quiz:ans:{guild_id}:{token}:{choice}:{correct}
        elif custom_id.startswith("quiz:ans:"):
            await interaction.response.defer()
            parts = custom_id.split(":")
            if len(parts) < 6:
                return
            try:
                guild_id    = int(parts[2])
                choice_idx  = int(parts[4])
                correct_idx = int(parts[5])
            except ValueError:
                return
            await self._cog._quiz_answer(interaction, guild_id, choice_idx, correct_idx)


# ── Party Cog ──────────────────────────────────────────────────────────

class Party(commands.Cog):
    def __init__(self, bot: "IrohaBot") -> None:
        self.bot    = bot
        self._states: dict[int, dict] = {}   # guild_id → state

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self.bot.add_view(PartyView(self))
        log.info("PartyView registered (persistent).")

    def _get_state(self, guild_id: int) -> dict:
        if guild_id not in self._states:
            self._states[guild_id] = {
                "active":       False,
                "dj_queue":     [],
                "current_dj":   None,
                "hype_score":   0,
                "hype_voters":  set(),
            }
        return self._states[guild_id]

    # ── コマンド ──────────────────────────────────────────────────

    @commands.hybrid_command(name="party")
    async def party(self, ctx: commands.Context) -> None:
        """パーティーモードパネルを表示する"""
        await _ack(ctx)
        guild_id = ctx.guild.id
        state    = self._get_state(guild_id)
        await _post_v2(self.bot, ctx.channel.id, _party_components(guild_id, state))

    @commands.hybrid_command(name="quiz")
    async def quiz(self, ctx: commands.Context) -> None:
        """曲当てクイズを開始する"""
        await _ack(ctx)
        guild_id    = ctx.guild.id
        music_state = self.bot.guild_manager.get(guild_id)

        if not music_state.current and not music_state.queue:
            await ctx.send("❌ キューに曲がありません。先に曲を追加してください。")
            return

        correct_track = music_state.current or music_state.queue[0]
        correct_title = correct_track["title"]

        # ダミー選択肢をキューから収集
        dummy_pool = [t["title"] for t in music_state.queue if t["title"] != correct_title]
        fallbacks  = ["Mystery Song A", "Unknown Track B", "Hidden Gem C", "Secret Hit D"]
        while len(dummy_pool) < 3:
            dummy_pool.append(fallbacks[len(dummy_pool) % len(fallbacks)])

        options = random.sample(dummy_pool[:8], 3) + [correct_title]
        random.shuffle(options)
        correct_idx = options.index(correct_title)

        token = uuid.uuid4().hex[:8]
        await _post_v2(
            self.bot, ctx.channel.id,
            _quiz_components(options, correct_idx, token, guild_id),
        )

    # ── Interaction ハンドラ ──────────────────────────────────────

    async def _update_panel(self, interaction: discord.Interaction, guild_id: int) -> None:
        state = self._get_state(guild_id)
        comps = _party_components(guild_id, state)
        await _edit_v2(self.bot, interaction.channel_id, interaction.message.id, comps)

    async def _toggle_party(self, interaction: discord.Interaction, guild_id: int) -> None:
        state = self._get_state(guild_id)
        state["active"] = not state["active"]
        if not state["active"]:
            state["hype_voters"].clear()
        await self._update_panel(interaction, guild_id)

    async def _join_dj(self, interaction: discord.Interaction, guild_id: int) -> None:
        state   = self._get_state(guild_id)
        user_id = interaction.user.id
        if user_id not in state["dj_queue"] and user_id != state["current_dj"]:
            state["dj_queue"].append(user_id)
        if state["current_dj"] is None and state["dj_queue"]:
            state["current_dj"] = state["dj_queue"].pop(0)
        await self._update_panel(interaction, guild_id)

    async def _next_dj(self, interaction: discord.Interaction, guild_id: int) -> None:
        state = self._get_state(guild_id)
        state["current_dj"] = state["dj_queue"].pop(0) if state["dj_queue"] else None
        await self._update_panel(interaction, guild_id)

    async def _add_hype(self, interaction: discord.Interaction, guild_id: int) -> None:
        state   = self._get_state(guild_id)
        user_id = interaction.user.id
        if user_id not in state["hype_voters"]:
            state["hype_voters"].add(user_id)
            state["hype_score"] += 5
        await self._update_panel(interaction, guild_id)

    async def _quiz_answer(
        self,
        interaction: discord.Interaction,
        guild_id: int,
        choice: int,
        correct: int,
    ) -> None:
        is_correct = (choice == correct)
        result_text = (
            f"🎉 **正解！** おめでとうございます！"
            if is_correct else
            "❌ **不正解...** また次回！"
        )
        comps = [
            {
                "type": 17,
                "accent_color": 0x57F287 if is_correct else 0xED4245,
                "components": [
                    {
                        "type": 10,
                        "content": (
                            f"## 🎵 クイズ結果\n"
                            f"{result_text}\n\n"
                            f"回答者: <@{interaction.user.id}>"
                        ),
                    }
                ],
            }
        ]
        await _edit_v2(self.bot, interaction.channel_id, interaction.message.id, comps)


async def setup(bot: "IrohaBot") -> None:
    await bot.add_cog(Party(bot))