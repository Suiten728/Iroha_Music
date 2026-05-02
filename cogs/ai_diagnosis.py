"""
cogs/ai_diagnosis.py — AI音楽診断システム
3問ランダム出題 → LayoutView UI → キュー自動生成
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from utils.ai_engine import pick_questions, calculate_result, QUESTIONS
from utils.audio_engine import YTDLSource

if TYPE_CHECKING:
    from bot import IrohaBot

log = logging.getLogger("iroha.ai_diagnosis")

# ─── セッション管理 ────────────────────────────────────────────────────
# guild_id -> {user_id -> DiagnosisSession}
_sessions: dict[int, dict[int, "DiagnosisSession"]] = {}


class DiagnosisSession:
    def __init__(self, questions: list[dict]) -> None:
        self.questions = questions
        self.current = 0
        self.answers: list[dict] = []

    @property
    def done(self) -> bool:
        return self.current >= len(self.questions)

    def current_q(self) -> dict | None:
        if self.done:
            return None
        return self.questions[self.current]

    def answer(self, option_value: str) -> None:
        q = self.current_q()
        if q is None:
            return
        opt = next((o for o in q["options"] if o["value"] == option_value), None)
        if opt:
            self.answers.append({"question_id": q["id"], "option_value": option_value, "option_data": opt})
        self.current += 1


# ─── Component v2 JSON ビルダー ──────────────────────────────────────

def _question_components(session: DiagnosisSession, guild_id: int, user_id: int) -> list[dict]:
    q = session.current_q()
    if q is None:
        return []
    total = len(session.questions)
    idx = session.current
    progress = "🟦" * idx + "⬛" * (total - idx)

    cat_labels = {"genre": "🎸 ジャンル", "mood": "😊 気分", "energy": "⚡ エネルギー", "lifestyle": "🌿 ライフスタイル"}
    cat = cat_labels.get(q["category"], q["category"])

    return [
        {
            "type": 17,
            "accent_color": 0xED4245,
            "components": [
                {
                    "type": 10,
                    "content": (
                        f"## 🎵 AI音楽診断\n"
                        f"**Q{idx+1}/{total}** — {cat}\n\n"
                        f"**{q['text']}**\n\n"
                        f"{progress}"
                    ),
                },
                {"type": 14, "spacing": 2},
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 3,
                            "custom_id": f"diag:answer:{guild_id}:{user_id}",
                            "placeholder": "回答を選択してください",
                            "options": [{"label": o["label"], "value": o["value"]} for o in q["options"]],
                        }
                    ],
                },
            ],
        }
    ]


def _result_components(result, guild_id: int) -> list[dict]:
    energy_bar = "🟩" * int(result.energy_score * 10) + "⬛" * (10 - int(result.energy_score * 10))
    genre_lines = "\n".join(
        f"　`{'█' * int(v*10):<10}` {g.upper()} ({v:.0%})"
        for g, v in sorted(result.genre_scores.items(), key=lambda x: -x[1])[:5]
    )

    return [
        {
            "type": 17,
            "accent_color": 0xFEE75C,
            "components": [
                {
                    "type": 10,
                    "content": (
                        f"## 🎯 AI診断結果\n"
                        f"**{result.type_label}**\n"
                        f"_{result.type_description}_"
                    ),
                },
                {"type": 14, "spacing": 2},
                {
                    "type": 10,
                    "content": (
                        f"**⚡ エネルギースコア: {result.energy_score:.0%}**\n"
                        f"{energy_bar}\n\n"
                        f"**🎵 ジャンル分析**\n{genre_lines}"
                    ),
                },
                {"type": 14, "spacing": 1},
                {
                    "type": 1,
                    "components": [
                        {"type": 2, "style": 1, "label": "🎵 推奨キューを生成", "custom_id": f"diag:gen_queue:{guild_id}"},
                        {"type": 2, "style": 2, "label": "🔁 もう一度診断", "custom_id": f"diag:restart:{guild_id}"},
                    ],
                },
            ],
        }
    ]


# ─── Persistent View ──────────────────────────────────────────────────

class DiagnosisView(discord.ui.View):
    def __init__(self, cog: "AIDiagnosis") -> None:
        super().__init__(timeout=None)
        self._cog = cog

    @discord.ui.select(
        custom_id="diag:answer",
        options=[discord.SelectOption(label="placeholder", value="placeholder")],
    )
    async def answer_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        await self._cog._handle_answer(interaction, select.values[0])

    @discord.ui.button(custom_id="diag:restart", label="🔁 もう一度診断", style=discord.ButtonStyle.secondary)
    async def restart_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._cog._start_diagnosis(interaction)

    @discord.ui.button(custom_id="diag:gen_queue", label="🎵 推奨キューを生成", style=discord.ButtonStyle.primary)
    async def gen_queue_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._cog._generate_queue(interaction)


class AIDiagnosis(commands.Cog):
    def __init__(self, bot: "IrohaBot") -> None:
        self.bot = bot
        self._last_results: dict[int, object] = {}

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self.bot.add_view(DiagnosisView(self))
        log.info("DiagnosisView registered (persistent).")

    @commands.hybrid_command(name="diagnose", aliases=["diag"])
    async def diagnose(self, ctx: commands.Context) -> None:
        """AI音楽診断を開始する（3問）"""
        # ── スラッシュ時: defer → _post_v2 → delete_original_response ──
        # defer しないと Discord が「インタラクション失敗」と表示する
        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.interaction.response.defer(thinking=True)

        guild_id = ctx.guild.id
        user_id = ctx.author.id
        questions = pick_questions(3)
        session = DiagnosisSession(questions)
        if guild_id not in _sessions:
            _sessions[guild_id] = {}
        _sessions[guild_id][user_id] = session

        comps = _question_components(session, guild_id, user_id)

        # Component v2 メッセージを HTTP 直送
        await self.bot.http.request(
            discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=ctx.channel.id),
            json={"flags": 1 << 15, "components": comps},
        )

        # スラッシュ時: thinking 表示（defer の応答）を削除
        if ctx.interaction:
            try:
                await ctx.interaction.delete_original_response()
            except Exception:
                pass

    async def _start_diagnosis(self, interaction: discord.Interaction) -> None:
        """ボタンから再診断を開始する"""
        # まず defer してタイムアウトを防ぐ
        if not interaction.response.is_done():
            await interaction.response.defer()

        guild_id = interaction.guild_id
        user_id = interaction.user.id
        questions = pick_questions(3)
        session = DiagnosisSession(questions)
        if guild_id not in _sessions:
            _sessions[guild_id] = {}
        _sessions[guild_id][user_id] = session

        comps = _question_components(session, guild_id, user_id)
        await interaction.client.http.request(
            discord.http.Route(
                "PATCH",
                "/channels/{channel_id}/messages/{message_id}",
                channel_id=interaction.channel_id,
                message_id=interaction.message.id,
            ),
            json={"flags": 1 << 15, "components": comps},
        )

    async def _handle_answer(self, interaction: discord.Interaction, value: str) -> None:
        # まず defer してタイムアウトを防ぐ
        if not interaction.response.is_done():
            await interaction.response.defer()

        guild_id = interaction.guild_id
        user_id = interaction.user.id
        guild_sessions = _sessions.get(guild_id, {})
        session = guild_sessions.get(user_id)
        if session is None:
            await interaction.followup.send("❌ セッションが見つかりません。`/diagnose` で再開してください。", ephemeral=True)
            return

        session.answer(value)

        if session.done:
            result = calculate_result(session.answers)
            self._last_results[user_id] = result

            try:
                await self.bot.db.execute(
                    """INSERT OR REPLACE INTO ai_profiles(guild_id, user_id, music_type, energy_score, genre_scores)
                       VALUES(?, ?, ?, ?, ?)""",
                    (guild_id, user_id, result.music_type, result.energy_score, json.dumps(result.genre_scores)),
                )
                await self.bot.db.commit()
            except Exception as e:
                log.warning(f"Failed to save ai_profile: {e}")

            comps = _result_components(result, guild_id)
        else:
            comps = _question_components(session, guild_id, user_id)

        await interaction.client.http.request(
            discord.http.Route(
                "PATCH",
                "/channels/{channel_id}/messages/{message_id}",
                channel_id=interaction.channel_id,
                message_id=interaction.message.id,
            ),
            json={"flags": 1 << 15, "components": comps},
        )

    async def _generate_queue(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()

        user_id = interaction.user.id
        result = self._last_results.get(user_id)
        if result is None:
            await interaction.followup.send("❌ 診断結果が見つかりません。先に診断してください。", ephemeral=True)
            return

        music_cog = self.bot.get_cog("Music")
        if music_cog is None:
            return

        added = 0
        for query in result.search_queries:
            tracks = await YTDLSource.search(query)
            if tracks:
                await music_cog._add_to_queue(interaction.guild_id, tracks[:2], user_id)
                added += len(tracks[:2])

        comps = [
            {
                "type": 17,
                "accent_color": 0x57F287,
                "components": [
                    {
                        "type": 10,
                        "content": (
                            f"✅ **{added}曲** をキューに追加しました！\n"
                            f"診断タイプ: **{result.type_label}**\n"
                            f"ボイスチャンネルに参加して `/play` で開始してください。"
                        ),
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


async def setup(bot: "IrohaBot") -> None:
    await bot.add_cog(AIDiagnosis(bot))
