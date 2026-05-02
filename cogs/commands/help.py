"""
cogs/commands/help.py — ヘルプコマンド
全コマンドの説明を Component v2 で表示する
"""

from __future__ import annotations

import discord
from discord.ext import commands


def _help_components() -> list[dict]:
    """ヘルプパネルの Component v2 JSON を生成する"""

    music_cmds = (
        "`/play <URL or 検索ワード>` — 音楽を再生 (エイリアス: `/p`)\n"
        "`/search <検索ワード>` — 検索して選択画面を表示 (エイリアス: `/s`)\n"
        "`/playlist <URL>` — プレイリストを丸ごと追加 (エイリアス: `/pl`)\n"
        "`/nowplaying` — 現在再生中の曲を表示 (エイリアス: `/np`, `/now`)\n"
        "`/queue` — キュー一覧を表示 (エイリアス: `/q`)\n"
        "`/skip` — 曲をスキップ（投票スキップ）\n"
        "`/pause` — 一時停止\n"
        "`/resume` — 再開\n"
        "`/stop` — 停止してキューをクリア\n"
        "`/leave` — ボイスチャンネルから切断 (エイリアス: `/dc`)\n"
        "`/volume <1-150>` — 音量を変更 (エイリアス: `/vol`)\n"
        "`/loop <none/one/all>` — ループモード設定\n"
        "`/shuffle` — シャッフル ON/OFF"
    )

    queue_cmds = (
        "`/remove <番号>` — キューから指定番号の曲を削除 (エイリアス: `/rm`)\n"
        "`/move <from> <to>` — キューの曲を移動\n"
        "`/clearqueue` — キューを全クリア (エイリアス: `/cq`)"
    )

    effect_cmds = (
        "`/eq` — イコライザーパネルを表示 (エイリアス: `/equalizer`)\n"
        "　　プリセット選択・Bass Boost・立体音響・リバーブを設定"
    )

    stats_cmds = (
        "`/stats` — サーバーの音楽統計を表示 (エイリアス: `/ranking`)\n"
        "`/mystats` — 自分の再生履歴を表示"
    )

    fun_cmds = (
        "`/party` — パーティーモードパネルを表示\n"
        "　　DJ制度・盛り上がりスコア・DJ交代\n"
        "`/quiz` — 曲当てクイズを開始\n"
        "`/diagnose` — AI音楽診断（3問）→ 推奨キュー生成 (エイリアス: `/diag`)"
    )

    other_cmds = (
        "`/ping` — Botの応答速度を測定\n"
        "`/help` — このヘルプを表示"
    )

    prefix_note = (
        "💡 スラッシュコマンド (`/`) とプレフィックスコマンド (`IM!`) の両方が使えます。\n"
        "例: `/play Lemon` = `IM!play Lemon`"
    )

    return [
        {
            "type": 17,
            "accent_color": 0x5865F2,
            "components": [
                {
                    "type": 10,
                    "content": "## 🎵 いろは Music — コマンド一覧",
                },
                {"type": 14, "spacing": 2},
                {
                    "type": 10,
                    "content": f"### 🎶 音楽再生\n{music_cmds}",
                },
                {"type": 14, "spacing": 1},
                {
                    "type": 10,
                    "content": f"### 📋 キュー管理\n{queue_cmds}",
                },
                {"type": 14, "spacing": 1},
                {
                    "type": 10,
                    "content": f"### 🎛️ オーディオエフェクト\n{effect_cmds}",
                },
                {"type": 14, "spacing": 1},
                {
                    "type": 10,
                    "content": f"### 📊 統計\n{stats_cmds}",
                },
                {"type": 14, "spacing": 1},
                {
                    "type": 10,
                    "content": f"### 🎉 エンタメ・診断\n{fun_cmds}",
                },
                {"type": 14, "spacing": 1},
                {
                    "type": 10,
                    "content": f"### 🔧 その他\n{other_cmds}",
                },
                {"type": 14, "spacing": 2},
                {
                    "type": 10,
                    "content": prefix_note,
                },
            ],
        }
    ]


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="help", description="コマンド一覧を表示します")
    async def help_cmd(self, ctx: commands.Context) -> None:
        """コマンド一覧を表示する"""
        # スラッシュ時: defer → Component v2 を HTTP 直送 → thinking 表示を削除
        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.interaction.response.defer(thinking=True)

        comps = _help_components()
        await self.bot.http.request(
            discord.http.Route(
                "POST", "/channels/{channel_id}/messages",
                channel_id=ctx.channel.id,
            ),
            json={"flags": 1 << 15, "components": comps},
        )

        # スラッシュ時: thinking 表示を削除
        if ctx.interaction:
            try:
                await ctx.interaction.delete_original_response()
            except Exception:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))
