"""
cogs/audio_effects.py — イコライザー / オーディオエフェクト設定
Guild別保存 / プリセット選択 / カスタムEQ設定
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from utils.audio_engine import PRESETS

if TYPE_CHECKING:
    from bot import IrohaBot

log = logging.getLogger("iroha.audio_effects")


def _eq_panel_components(audio_cfg: dict) -> list[dict]:
    preset = audio_cfg.get("preset", "flat")
    bass = audio_cfg.get("bass_boost", 0)
    surround = bool(audio_cfg.get("surround", 0))
    reverb = bool(audio_cfg.get("reverb", 0))

    preset_options = [
        {"label": "🎵 フラット (デフォルト)", "value": "flat", "description": "エフェクトなし"},
        {"label": "🔊 Bass Boost", "value": "bass_boost", "description": "低域強化"},
        {"label": "🎤 Vocal Clear", "value": "vocal_clear", "description": "ボーカル強調"},
        {"label": "🌐 3D Surround", "value": "surround_3d", "description": "立体音響"},
        {"label": "🏟️ Live Hall", "value": "live_hall", "description": "ホール残響"},
        {"label": "🌙 Night Mode", "value": "night_mode", "description": "夜間向け低音抑制"},
    ]

    bass_options = [
        {"label": f"Bass Boost: {v}dB", "value": str(v)}
        for v in [0, 3, 6, 9, 12]
    ]

    return [
        {
            "type": 17,
            "accent_color": 0x5865F2,
            "components": [
                {
                    "type": 10,
                    "content": (
                        f"## 🎛️ オーディオエフェクト設定\n"
                        f"現在のプリセット: **{preset}**　"
                        f"Bass: **+{bass}dB**　"
                        f"立体音響: **{'ON' if surround else 'OFF'}**　"
                        f"リバーブ: **{'ON' if reverb else 'OFF'}**"
                    ),
                },
                {"type": 14, "spacing": 2},
                {
                    "type": 10,
                    "content": "**🎚️ プリセット選択**",
                },
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 3,
                            "custom_id": "eq:preset_select",
                            "placeholder": f"プリセット: {preset}",
                            "options": preset_options,
                        }
                    ],
                },
                {
                    "type": 10,
                    "content": "**🔊 Bass Boost レベル**",
                },
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 3,
                            "custom_id": "eq:bass_select",
                            "placeholder": f"Bass: +{bass}dB",
                            "options": bass_options,
                        }
                    ],
                },
                {"type": 14, "spacing": 1},
                {
                    "type": 1,
                    "components": [
                        {"type": 2, "style": 1, "label": "🌐 立体音響 ON/OFF", "custom_id": "eq:toggle_surround"},
                        {"type": 2, "style": 1, "label": "🏟️ リバーブ ON/OFF", "custom_id": "eq:toggle_reverb"},
                        {"type": 2, "style": 4, "label": "↩ リセット", "custom_id": "eq:reset"},
                    ],
                },
            ],
        }
    ]


class EQView(discord.ui.View):
    def __init__(self, cog: "AudioEffects") -> None:
        super().__init__(timeout=None)
        self._cog = cog

    @discord.ui.select(
        custom_id="eq:preset_select",
        options=[discord.SelectOption(label="フラット", value="flat")],
    )
    async def preset_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        await self._cog._apply_preset(interaction, select.values[0])

    @discord.ui.select(
        custom_id="eq:bass_select",
        options=[discord.SelectOption(label="0dB", value="0")],
    )
    async def bass_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        await self._cog._set_bass(interaction, int(select.values[0]))

    @discord.ui.button(custom_id="eq:toggle_surround", label="🌐 立体音響", style=discord.ButtonStyle.primary)
    async def surround_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._cog._toggle_surround(interaction)

    @discord.ui.button(custom_id="eq:toggle_reverb", label="🏟️ リバーブ", style=discord.ButtonStyle.primary)
    async def reverb_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._cog._toggle_reverb(interaction)

    @discord.ui.button(custom_id="eq:reset", label="↩ リセット", style=discord.ButtonStyle.danger)
    async def reset_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._cog._reset_eq(interaction)


class AudioEffects(commands.Cog):
    def __init__(self, bot: "IrohaBot") -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self.bot.add_view(EQView(self))
        log.info("EQView registered (persistent).")

    @commands.command(name="eq", aliases=["equalizer"])
    async def eq_panel(self, ctx: commands.Context) -> None:
        """イコライザーパネルを表示する"""
        audio_cfg = await self.bot.guild_manager.get_audio_settings(ctx.guild.id)
        comps = _eq_panel_components(audio_cfg)
        await self.bot.http.request(
            discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=ctx.channel.id),
            json={"flags": 1 << 15, "components": comps},
        )

    async def _save_audio_settings(self, guild_id: int, **kwargs) -> None:
        set_clauses = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [guild_id]
        await self.bot.db.execute(
            f"UPDATE audio_settings SET {set_clauses}, updated_at = datetime('now') WHERE guild_id = ?",
            tuple(values),
        )
        await self.bot.db.commit()

    async def _refresh_panel(self, interaction: discord.Interaction) -> None:
        audio_cfg = await self.bot.guild_manager.get_audio_settings(interaction.guild_id)
        comps = _eq_panel_components(audio_cfg)
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

    async def _apply_preset(self, interaction: discord.Interaction, preset: str) -> None:
        guild_id = interaction.guild_id
        state = self.bot.guild_manager.get(guild_id)
        preset_data = PRESETS.get(preset, {})

        bass_boost = preset_data.get("bass_boost", 0)
        surround = 1 if preset_data.get("surround") else 0
        reverb = 1 if preset_data.get("reverb", 0) > 0 else 0

        state.preset = preset
        state.bass_boost = bass_boost
        state.surround = bool(surround)

        await self._save_audio_settings(guild_id, preset=preset, bass_boost=bass_boost, surround=surround, reverb=reverb)
        await self._refresh_panel(interaction)

    async def _set_bass(self, interaction: discord.Interaction, level: int) -> None:
        guild_id = interaction.guild_id
        state = self.bot.guild_manager.get(guild_id)
        state.bass_boost = level
        await self._save_audio_settings(guild_id, bass_boost=level)
        await self._refresh_panel(interaction)

    async def _toggle_surround(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id
        state = self.bot.guild_manager.get(guild_id)
        state.surround = not state.surround
        await self._save_audio_settings(guild_id, surround=1 if state.surround else 0)
        await self._refresh_panel(interaction)

    async def _toggle_reverb(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id
        audio_cfg = await self.bot.guild_manager.get_audio_settings(guild_id)
        new_val = 0 if audio_cfg.get("reverb", 0) else 1
        await self._save_audio_settings(guild_id, reverb=new_val)
        await self._refresh_panel(interaction)

    async def _reset_eq(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id
        state = self.bot.guild_manager.get(guild_id)
        state.preset = "flat"
        state.bass_boost = 0
        state.surround = False
        await self._save_audio_settings(guild_id, preset="flat", bass_boost=0, surround=0, reverb=0, eq_bands="{}")
        await self._refresh_panel(interaction)


async def setup(bot: "IrohaBot") -> None:
    await bot.add_cog(AudioEffects(bot))
