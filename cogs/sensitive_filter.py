"""
cogs/sensitive_filter.py — センシティブ楽曲事前警告システム
曲追加時に自動スキャン → LayoutView確認UI
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from utils.filter_engine import scan_track, format_flag_summary, FLAG_LABELS, FLAG_COLORS

if TYPE_CHECKING:
    from bot import IrohaBot

log = logging.getLogger("iroha.sensitive_filter")

# 保留中トラック: guild_id -> {token -> track}
_pending: dict[int, dict[str, dict]] = {}


def _warning_components(track: dict, flags: list[str], token: str, guild_id: int) -> list[dict]:
    flag_text = "\n".join(f"・{FLAG_LABELS.get(f, f)}" for f in flags)
    accent = FLAG_COLORS.get(flags[0], 0xFF6B6B) if flags else 0xFF6B6B

    return [
        {
            "type": 17,
            "accent_color": accent,
            "components": [
                {
                    "type": 10,
                    "content": (
                        f"## ⚠️ センシティブコンテンツ警告\n"
                        f"**{track['title']}**\n\n"
                        f"この楽曲には以下の表現が含まれる可能性があります：\n"
                        f"{flag_text}"
                    ),
                },
                {"type": 14, "spacing": 1},
                {"type": 10, "content": "再生しますか？"},
                {
                    "type": 1,
                    "components": [
                        {"type": 2, "style": 1, "label": "✅ 再生する", "custom_id": f"sensitive:play:{guild_id}:{token}"},
                        {"type": 2, "style": 4, "label": "❌ キャンセル", "custom_id": f"sensitive:cancel:{guild_id}:{token}"},
                        {"type": 2, "style": 2, "label": "ℹ️ 詳細を見る", "custom_id": f"sensitive:detail:{guild_id}:{token}"},
                    ],
                },
            ],
        }
    ]


def _detail_components(track: dict, flags: list[str], token: str, guild_id: int) -> list[dict]:
    details = {
        "sexual": "この楽曲は性的な表現を含むと判定されました。\n18歳未満には不適切な可能性があります。",
        "violence": "この楽曲は暴力的な表現（歌詞・タイトル等）を含むと判定されました。",
        "depression": "この楽曲は鬱・自傷的な表現を含むと判定されました。\n精神的に辛い状況の方への配慮が必要です。",
    }
    detail_text = "\n\n".join(details.get(f, "") for f in flags if f in details)

    return [
        {
            "type": 17,
            "accent_color": 0xED4245,
            "components": [
                {
                    "type": 10,
                    "content": (
                        f"## ℹ️ センシティブ詳細情報\n"
                        f"**{track['title']}**\n\n"
                        f"{detail_text}"
                    ),
                },
                {"type": 14, "spacing": 1},
                {
                    "type": 1,
                    "components": [
                        {"type": 2, "style": 1, "label": "✅ 理解した上で再生", "custom_id": f"sensitive:play:{guild_id}:{token}"},
                        {"type": 2, "style": 4, "label": "❌ キャンセル", "custom_id": f"sensitive:cancel:{guild_id}:{token}"},
                    ],
                },
            ],
        }
    ]


class SensitiveFilterView(discord.ui.View):
    def __init__(self, cog: "SensitiveFilter") -> None:
        super().__init__(timeout=None)
        self._cog = cog

    @discord.ui.button(custom_id="sensitive:play", label="✅ 再生する", style=discord.ButtonStyle.primary)
    async def play_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        # custom_id から guild_id, token を取得
        parts = interaction.data.get("custom_id", "").split(":")
        if len(parts) < 4:
            return
        guild_id = int(parts[2])
        token = parts[3]
        await self._cog._approve(interaction, guild_id, token)

    @discord.ui.button(custom_id="sensitive:cancel", label="❌ キャンセル", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        parts = interaction.data.get("custom_id", "").split(":")
        if len(parts) < 4:
            return
        guild_id = int(parts[2])
        token = parts[3]
        _pending.get(guild_id, {}).pop(token, None)
        try:
            await interaction.message.delete()
        except Exception:
            pass
        await interaction.response.defer()

    @discord.ui.button(custom_id="sensitive:detail", label="ℹ️ 詳細を見る", style=discord.ButtonStyle.secondary)
    async def detail_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        parts = interaction.data.get("custom_id", "").split(":")
        if len(parts) < 4:
            return
        guild_id = int(parts[2])
        token = parts[3]
        track_info = _pending.get(guild_id, {}).get(token)
        if not track_info:
            await interaction.response.defer()
            return
        flags = track_info.get("flags", [])
        track = track_info.get("track", {})
        comps = _detail_components(track, flags, token, guild_id)
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


class SensitiveFilter(commands.Cog):
    def __init__(self, bot: "IrohaBot") -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self.bot.add_view(SensitiveFilterView(self))
        log.info("SensitiveFilterView registered (persistent).")

    async def check_and_warn(
        self,
        channel: discord.TextChannel,
        guild_id: int,
        track: dict,
        requester_id: int,
    ) -> bool:
        """
        センシティブチェックを行い、警告が必要な場合はUIを送信してFalseを返す。
        問題なければTrueを返す。
        """
        # guild設定確認
        settings = await self.bot.guild_manager.get_settings(guild_id)
        if not settings.get("sensitive_warn", 1):
            return True  # 警告OFF

        # キャッシュ確認
        cached = await self.bot.db.fetchone(
            "SELECT flags FROM sensitive_cache WHERE url = ?", (track.get("webpage_url", ""),)
        )
        if cached:
            flags = json.loads(cached["flags"])
        else:
            flags = scan_track(track)
            if track.get("webpage_url"):
                try:
                    await self.bot.db.execute(
                        "INSERT OR REPLACE INTO sensitive_cache(url, flags) VALUES(?, ?)",
                        (track["webpage_url"], json.dumps(flags)),
                    )
                    await self.bot.db.commit()
                except Exception:
                    pass

        if not flags:
            return True

        # トークン生成
        import uuid
        token = uuid.uuid4().hex[:8]
        if guild_id not in _pending:
            _pending[guild_id] = {}
        _pending[guild_id][token] = {"track": track, "flags": flags, "requester_id": requester_id}

        comps = _warning_components(track, flags, token, guild_id)
        await self.bot.http.request(
            discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=channel.id),
            json={"flags": 1 << 15, "components": comps},
        )
        return False

    async def _approve(self, interaction: discord.Interaction, guild_id: int, token: str) -> None:
        track_info = _pending.get(guild_id, {}).pop(token, None)
        if not track_info:
            await interaction.response.defer()
            return

        track = track_info["track"]
        requester_id = track_info["requester_id"]

        music_cog = self.bot.get_cog("Music")
        if music_cog:
            await music_cog._add_to_queue(guild_id, [track], requester_id)
            vc: discord.VoiceClient | None = interaction.guild.voice_client if interaction.guild else None
            if vc and not vc.is_playing():
                await music_cog._advance(guild_id)

        comps = [
            {
                "type": 17,
                "accent_color": 0x57F287,
                "components": [
                    {"type": 10, "content": f"✅ **{track['title']}** をキューに追加しました。"},
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
    await bot.add_cog(SensitiveFilter(bot))
