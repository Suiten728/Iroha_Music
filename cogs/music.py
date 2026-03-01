"""
cogs/music.py — 再生・キュー管理・基本コントロール
LayoutView / Component v2 を使用
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from utils.audio_engine import YTDLSource, make_ffmpeg_source, PRESETS
from utils.filter_engine import scan_track, format_flag_summary, FLAG_LABELS

if TYPE_CHECKING:
    from bot import IrohaBot

log = logging.getLogger("iroha.music")

# ─── NoCopy ミックスイン ────────────────────────────────────────────
class NoCopy:
    """LayoutView の deepcopy を回避するミックスイン"""
    def __deepcopy__(self, memo):
        return self


# ─── LayoutView 送信ヘルパー ─────────────────────────────────────────
async def send_v2(
    ctx_or_channel: commands.Context | discord.TextChannel | discord.Interaction,
    components: list[dict],
) -> None:
    """IS_COMPONENTS_V2 フラグ付きでメッセージをHTTP直送する"""
    if isinstance(ctx_or_channel, commands.Context):
        channel_id = ctx_or_channel.channel.id
        bot = ctx_or_channel.bot
    elif isinstance(ctx_or_channel, discord.Interaction):
        channel_id = ctx_or_channel.channel_id
        bot = ctx_or_channel.client
    else:
        channel_id = ctx_or_channel.id
        bot = ctx_or_channel._state._get_client()  # type: ignore

    await bot.http.request(
        discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=channel_id),
        json={"flags": 1 << 15, "components": components},
    )


async def edit_v2(
    interaction: discord.Interaction,
    components: list[dict],
) -> None:
    """既存メッセージを IS_COMPONENTS_V2 フラグ付きで編集"""
    await interaction.client.http.request(
        discord.http.Route(
            "PATCH",
            "/channels/{channel_id}/messages/{message_id}",
            channel_id=interaction.channel_id,
            message_id=interaction.message.id,
        ),
        json={"flags": 1 << 15, "components": components},
    )


async def send_v2_interaction(
    interaction: discord.Interaction,
    components: list[dict],
    ephemeral: bool = False,
) -> None:
    """Interaction の response として IS_COMPONENTS_V2 を送信"""
    flags = (1 << 15) | (1 << 6 if ephemeral else 0)
    await interaction.response.send_message(
        components=components,  # type: ignore — discord.py 2.6.x supports this
    )


# ─── Component v2 JSON ビルダー ──────────────────────────────────────

def _now_playing_components(track: dict, volume: int, loop_mode: str, pos: int, total: int) -> list[dict]:
    dur = YTDLSource.format_duration(track.get("duration", 0))
    queue_text = f"キュー: {pos}/{total}曲"
    loop_icon = {"none": "🔁", "one": "🔂", "all": "🔁"}[loop_mode]
    loop_label = {"none": "ループなし", "one": "1曲ループ", "all": "全体ループ"}[loop_mode]

    return [
        {
            "type": 17,  # Container
            "accent_color": 0x5865F2,
            "components": [
                {
                    "type": 10,
                    "content": f"## 🎵 Now Playing\n**{track['title']}**",
                },
                {"type": 14, "spacing": 1},  # Separator small
                {
                    "type": 9,  # Section
                    "components": [{"type": 10, "content": f"⏱️ {dur}　🔊 音量 {volume}%\n{loop_icon} {loop_label}　📋 {queue_text}"}],
                    "accessory": {
                        "type": 2, "style": 5,
                        "label": "YouTube",
                        "url": track.get("webpage_url", "https://youtube.com"),
                    },
                },
                {"type": 14, "spacing": 2},  # Separator large
                {
                    "type": 1,  # ActionRow — ボタン
                    "components": [
                        {"type": 2, "style": 4, "label": "⏭ スキップ", "custom_id": "music:skip"},
                        {"type": 2, "style": 1, "label": "⏸ 一時停止", "custom_id": "music:pause"},
                        {"type": 2, "style": 1, "label": "▶ 再開", "custom_id": "music:resume"},
                        {"type": 2, "style": 2, "label": "⏹ 停止", "custom_id": "music:stop"},
                    ],
                },
                {
                    "type": 1,  # ActionRow — セレクト（ループ）
                    "components": [
                        {
                            "type": 3,  # StringSelect
                            "custom_id": "music:loop_select",
                            "placeholder": f"ループ設定: {loop_label}",
                            "options": [
                                {"label": "🔁 ループなし", "value": "none"},
                                {"label": "🔂 1曲ループ", "value": "one"},
                                {"label": "🔁 全体ループ", "value": "all"},
                            ],
                        }
                    ],
                },
            ],
        }
    ]


def _search_result_components(results: list[dict], query: str) -> list[dict]:
    options = [
        {
            "label": f"{i+1}. {r['title'][:80]}",
            "value": str(i),
            "description": f"⏱ {YTDLSource.format_duration(r.get('duration', 0))}",
        }
        for i, r in enumerate(results[:5])
    ]
    return [
        {
            "type": 17,
            "accent_color": 0x57F287,
            "components": [
                {"type": 10, "content": f"## 🔍 検索結果: `{query}`\n曲を選択してください"},
                {"type": 14, "spacing": 1},
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 3,
                            "custom_id": "music:search_select",
                            "placeholder": "再生する曲を選択...",
                            "options": options,
                        }
                    ],
                },
                {
                    "type": 1,
                    "components": [
                        {"type": 2, "style": 4, "label": "キャンセル", "custom_id": "music:search_cancel"},
                    ],
                },
            ],
        }
    ]


def _queue_list_components(queue: list, page: int = 0) -> list[dict]:
    page_size = 8
    start = page * page_size
    page_items = queue[start:start + page_size]
    total_pages = max(1, (len(queue) + page_size - 1) // page_size)

    lines = []
    for i, track in enumerate(page_items, start=start + 1):
        dur = YTDLSource.format_duration(track.get("duration", 0))
        lines.append(f"`{i:02d}.` **{track['title'][:50]}** `{dur}`")

    content = "\n".join(lines) if lines else "キューは空です"

    components: list[dict] = [
        {
            "type": 17,
            "accent_color": 0xFEE75C,
            "components": [
                {"type": 10, "content": f"## 📋 キュー一覧 ({len(queue)}曲) — {page+1}/{total_pages}ページ"},
                {"type": 14, "spacing": 1},
                {"type": 10, "content": content},
            ],
        }
    ]

    # ページネーションボタン
    nav_buttons = []
    if page > 0:
        nav_buttons.append({"type": 2, "style": 1, "label": "◀ 前へ", "custom_id": f"music:queue_page:{page-1}"})
    if page < total_pages - 1:
        nav_buttons.append({"type": 2, "style": 1, "label": "次へ ▶", "custom_id": f"music:queue_page:{page+1}"})
    nav_buttons.append({"type": 2, "style": 4, "label": "🔀 シャッフル", "custom_id": "music:shuffle"})
    nav_buttons.append({"type": 2, "style": 2, "label": "🗑 全クリア", "custom_id": "music:queue_clear"})

    if nav_buttons:
        components[0]["components"].append({"type": 1, "components": nav_buttons})

    return components


# ─── Persistent Interaction View ─────────────────────────────────────

class MusicControlView(discord.ui.View):
    """
    add_view 登録用 Persistent View。
    コンポーネントのコールバックを受け取るために存在する。
    """

    def __init__(self, cog: "Music") -> None:
        super().__init__(timeout=None)
        self._cog = cog

    @discord.ui.button(custom_id="music:skip", label="⏭ スキップ", style=discord.ButtonStyle.danger)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self._cog._do_skip(interaction)

    @discord.ui.button(custom_id="music:pause", label="⏸ 一時停止", style=discord.ButtonStyle.primary)
    async def pause_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self._cog._do_pause(interaction)

    @discord.ui.button(custom_id="music:resume", label="▶ 再開", style=discord.ButtonStyle.primary)
    async def resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self._cog._do_resume(interaction)

    @discord.ui.button(custom_id="music:stop", label="⏹ 停止", style=discord.ButtonStyle.secondary)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self._cog._do_stop(interaction)

    @discord.ui.button(custom_id="music:shuffle", label="🔀 シャッフル", style=discord.ButtonStyle.danger)
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self._cog._do_shuffle(interaction)

    @discord.ui.button(custom_id="music:queue_clear", label="🗑 全クリア", style=discord.ButtonStyle.secondary)
    async def clear_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self._cog._do_clear(interaction)

    @discord.ui.select(custom_id="music:loop_select", options=[
        discord.SelectOption(label="ループなし", value="none"),
        discord.SelectOption(label="1曲ループ", value="one"),
        discord.SelectOption(label="全体ループ", value="all"),
    ])
    async def loop_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        await interaction.response.defer()
        await self._cog._do_loop(interaction, select.values[0])

    @discord.ui.select(custom_id="music:search_select", options=[
        discord.SelectOption(label="placeholder", value="0"),
    ])
    async def search_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        await interaction.response.defer()
        await self._cog._do_search_select(interaction, select.values[0])

    @discord.ui.button(custom_id="music:search_cancel", label="キャンセル", style=discord.ButtonStyle.secondary)
    async def search_cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.message.delete()
        await interaction.response.defer()

    async def _handle_queue_page(self, interaction: discord.Interaction, page: int) -> None:
        state = self._cog.bot.guild_manager.get(interaction.guild_id)
        await edit_v2(interaction, _queue_list_components(state.queue, page))
        await interaction.response.defer()


# ─── Music Cog ────────────────────────────────────────────────────────

class Music(commands.Cog):
    def __init__(self, bot: "IrohaBot") -> None:
        self.bot = bot
        self._search_cache: dict[int, list[dict]] = {}  # guild_id -> results

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self.bot.add_view(MusicControlView(self))
        log.info("MusicControlView registered (persistent).")

    # ─── 接続ヘルパー ─────────────────────────────────────────────────

    async def _ensure_voice(self, ctx: commands.Context) -> discord.VoiceClient | None:
        if ctx.author.voice is None:
            await ctx.send("❌ まずボイスチャンネルに参加してください。")
            return None
        guild_id = ctx.guild.id
        vc: discord.VoiceClient | None = ctx.voice_client
        if vc is None or not vc.is_connected():
            vc = await ctx.author.voice.channel.connect()
        elif ctx.author.voice.channel != vc.channel:
            await vc.move_to(ctx.author.voice.channel)
        await self.bot.guild_manager.ensure_guild(guild_id)
        return vc

    # ─── キュー追加 & 再生エンジン ────────────────────────────────────

    async def _add_to_queue(self, guild_id: int, tracks: list[dict], requester_id: int) -> None:
        state = self.bot.guild_manager.get(guild_id)
        settings = await self.bot.guild_manager.get_settings(guild_id)
        max_q = settings.get("max_queue", 200)
        for track in tracks:
            if len(state.queue) >= max_q:
                break
            track["requester_id"] = requester_id
            state.queue.append(track)

    def _after_track(self, guild_id: int, error: Exception | None) -> None:
        if error:
            log.error(f"[Guild {guild_id}] Player error: {error}")
        state = self.bot.guild_manager.get(guild_id)
        state.is_playing = False
        asyncio.run_coroutine_threadsafe(self._advance(guild_id), self.bot.loop)

    async def _advance(self, guild_id: int) -> None:
        state = self.bot.guild_manager.get(guild_id)
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        vc: discord.VoiceClient | None = guild.voice_client

        # ループ処理
        if state.loop_mode == "one" and state.current:
            pass  # 同じ曲を再度追加
        elif state.loop_mode == "all" and state.current:
            state.queue.append(state.current)

        if not state.queue:
            state.current = None
            await self._schedule_auto_leave(guild_id, guild)
            return

        # シャッフル
        if state.shuffle:
            import random
            random.shuffle(state.queue)

        next_track = state.queue.pop(0)
        state.current = next_track
        await self._play_track(guild_id, vc, next_track)

    async def _play_track(self, guild_id: int, vc: discord.VoiceClient, track: dict) -> None:
        state = self.bot.guild_manager.get(guild_id)
        audio_cfg = await self.bot.guild_manager.get_audio_settings(guild_id)
        import json
        eq_bands = json.loads(audio_cfg.get("eq_bands", "{}"))

        # ストリームURLは期限付きのため、再生直前に webpage_url から最新を取得する
        webpage_url = track.get("webpage_url", "")
        stream_url = await YTDLSource.get_stream_url(webpage_url)
        if not stream_url:
            log.error(f"[Guild {guild_id}] ストリームURL取得失敗: {webpage_url}")
            # 取得失敗時は次の曲へスキップ
            self._after_track(guild_id, None)
            return

        source = make_ffmpeg_source(
            stream_url,
            volume=state.volume,
            bass_boost=audio_cfg.get("bass_boost", 0),
            surround=bool(audio_cfg.get("surround", 0)),
            reverb_level=0.0,
            eq_bands=eq_bands if eq_bands else None,
        )

        vc.play(source, after=lambda e: self._after_track(guild_id, e))
        state.is_playing = True
        state.skip_votes.clear()

        # 再生統計記録
        await self._record_stat(guild_id, track)

        # Now Playing UI 送信
        channel = self.bot.get_channel(
            (await self.bot.guild_manager.get_settings(guild_id)).get("music_channel_id") or vc.channel.id
        )
        if channel and isinstance(channel, discord.TextChannel):
            settings = await self.bot.guild_manager.get_settings(guild_id)
            comps = _now_playing_components(
                track,
                int(state.volume * 100),
                state.loop_mode,
                0,
                len(state.queue),
            )
            try:
                await self.bot.http.request(
                    discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=channel.id),
                    json={"flags": 1 << 15, "components": comps},
                )
            except Exception as e:
                log.warning(f"Failed to send NowPlaying UI: {e}")

    async def _record_stat(self, guild_id: int, track: dict) -> None:
        try:
            await self.bot.db.execute(
                """INSERT INTO music_stats(guild_id, user_id, title, url, duration)
                   VALUES(?, ?, ?, ?, ?)""",
                (guild_id, track.get("requester_id", 0), track["title"], track.get("webpage_url", ""), track.get("duration", 0)),
            )
            await self.bot.db.commit()
        except Exception as e:
            log.warning(f"Failed to record stat: {e}")

    async def _schedule_auto_leave(self, guild_id: int, guild: discord.Guild) -> None:
        state = self.bot.guild_manager.get(guild_id)
        settings = await self.bot.guild_manager.get_settings(guild_id)
        delay = settings.get("auto_leave_sec", 300)

        async def _leave():
            await asyncio.sleep(delay)
            vc: discord.VoiceClient | None = guild.voice_client
            if vc and vc.is_connected() and not vc.is_playing():
                await vc.disconnect()
                log.info(f"[Guild {guild_id}] Auto-disconnected after {delay}s of inactivity.")

        if state.auto_leave_task:
            state.auto_leave_task.cancel()
        state.auto_leave_task = asyncio.create_task(_leave())

    # ─── コマンド ────────────────────────────────────────────────────

    @commands.hybrid_command(name="play", aliases=["p"])
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """URLまたは検索ワードで音楽を再生する"""
        try:
            vc = await self._ensure_voice(ctx)
            if vc is None:
                return

            async with ctx.typing():
                results = await YTDLSource.search(query)

            if not results:
                await ctx.send("❌ 検索結果が見つかりませんでした。")
                return

            if YTDLSource._is_url(query) and len(results) == 1:
                # 直接再生
                track = results[0]
                await self._add_to_queue(ctx.guild.id, [track], ctx.author.id)
                if not vc.is_playing():
                    await self._advance(ctx.guild.id)
                else:
                    await ctx.send(f"✅ **{track['title']}** をキューに追加しました。")
            else:
                # 検索結果表示（LayoutView）
                self._search_cache[ctx.guild.id] = results
                comps = _search_result_components(results[:5], query)
                await send_v2(ctx, comps)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await ctx.send(f"```\n{type(e).__name__}: {e}\n```")

    @commands.hybrid_command(name="search", aliases=["s"])
    async def search(self, ctx: commands.Context, *, query: str) -> None:
        """検索して選択画面を出す"""
        await self.play(ctx, query=query)

    @commands.hybrid_command(name="playlist", aliases=["pl"])
    async def playlist(self, ctx: commands.Context, url: str) -> None:
        """プレイリストURLを丸ごと追加する"""
        try:
            vc = await self._ensure_voice(ctx)
            if vc is None:
                return
            async with ctx.typing():
                tracks = await YTDLSource.fetch_playlist(url)
            if not tracks:
                await ctx.send("❌ プレイリストを取得できませんでした。")
                return
            await self._add_to_queue(ctx.guild.id, tracks, ctx.author.id)
            await ctx.send(f"✅ **{len(tracks)}曲** をキューに追加しました。")
            if not ctx.voice_client.is_playing():
                await self._advance(ctx.guild.id)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await ctx.send(f"```\n{type(e).__name__}: {e}\n```")

    @commands.hybrid_command(name="queue", aliases=["q"])
    async def queue(self, ctx: commands.Context) -> None:
        """キューを表示する"""
        state = self.bot.guild_manager.get(ctx.guild.id)
        comps = _queue_list_components(state.queue, 0)
        await send_v2(ctx, comps)

    @commands.hybrid_command(name="volume", aliases=["vol"])
    async def volume(self, ctx: commands.Context, vol: int) -> None:
        """音量を変更する (1-150)"""
        if not 1 <= vol <= 150:
            await ctx.send("❌ 音量は 1〜150 で指定してください。")
            return
        state = self.bot.guild_manager.get(ctx.guild.id)
        state.volume = vol / 100
        if ctx.voice_client and ctx.voice_client.source:
            ctx.voice_client.source.volume = state.volume
        await ctx.send(f"🔊 音量を **{vol}%** に設定しました。")

    @commands.hybrid_command(name="skip")
    async def skip(self, ctx: commands.Context) -> None:
        """曲をスキップする（投票スキップ）"""
        state = self.bot.guild_manager.get(ctx.guild.id)
        vc = ctx.voice_client
        if not vc or not vc.is_playing():
            await ctx.send("❌ 再生中の曲がありません。")
            return
        state.skip_votes.add(ctx.author.id)
        members = [m for m in vc.channel.members if not m.bot]
        needed = max(1, len(members) // 2)
        votes = len(state.skip_votes)
        if votes >= needed:
            vc.stop()
            await ctx.send(f"⏭ スキップしました。({votes}/{needed} 票)")
        else:
            await ctx.send(f"🗳 スキップ投票: {votes}/{needed} 票")

    @commands.hybrid_command(name="stop")
    async def stop(self, ctx: commands.Context) -> None:
        """再生を停止してキューをクリア"""
        state = self.bot.guild_manager.get(ctx.guild.id)
        state.queue.clear()
        state.current = None
        if ctx.voice_client:
            ctx.voice_client.stop()
        await ctx.send("⏹ 停止しました。")

    @commands.hybrid_command(name="pause")
    async def pause(self, ctx: commands.Context) -> None:
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸ 一時停止しました。")

    @commands.hybrid_command(name="resume")
    async def resume(self, ctx: commands.Context) -> None:
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶ 再開しました。")

    @commands.hybrid_command(name="loop")
    async def loop(self, ctx: commands.Context, mode: str = "one") -> None:
        """ループモード設定: none / one / all"""
        mode = mode.lower()
        if mode not in ("none", "one", "all"):
            await ctx.send("❌ mode は `none` / `one` / `all` で指定してください。")
            return
        state = self.bot.guild_manager.get(ctx.guild.id)
        state.loop_mode = mode
        labels = {"none": "ループなし", "one": "1曲ループ", "all": "全体ループ"}
        await ctx.send(f"🔁 ループを **{labels[mode]}** に設定しました。")

    @commands.hybrid_command(name="shuffle")
    async def shuffle(self, ctx: commands.Context) -> None:
        """シャッフルON/OFF"""
        state = self.bot.guild_manager.get(ctx.guild.id)
        state.shuffle = not state.shuffle
        status = "ON" if state.shuffle else "OFF"
        await ctx.send(f"🔀 シャッフルを **{status}** にしました。")

    @commands.hybrid_command(name="leave", aliases=["dc"])
    async def leave(self, ctx: commands.Context) -> None:
        """ボイスチャンネルから切断"""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("👋 切断しました。")

    # ─── Interaction コールバック ─────────────────────────────────────

    async def _do_skip(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        vc: discord.VoiceClient | None = guild.voice_client if guild else None
        if vc and vc.is_playing():
            vc.stop()

    async def _do_pause(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        vc: discord.VoiceClient | None = guild.voice_client if guild else None
        if vc and vc.is_playing():
            vc.pause()

    async def _do_resume(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        vc: discord.VoiceClient | None = guild.voice_client if guild else None
        if vc and vc.is_paused():
            vc.resume()

    async def _do_stop(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        state = self.bot.guild_manager.get(guild.id)
        state.queue.clear()
        state.current = None
        vc: discord.VoiceClient | None = guild.voice_client
        if vc:
            vc.stop()

    async def _do_loop(self, interaction: discord.Interaction, mode: str) -> None:
        if interaction.guild is None:
            return
        state = self.bot.guild_manager.get(interaction.guild.id)
        state.loop_mode = mode

    async def _do_shuffle(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        import random
        state = self.bot.guild_manager.get(interaction.guild.id)
        random.shuffle(state.queue)
        comps = _queue_list_components(state.queue, 0)
        await edit_v2(interaction, comps)

    async def _do_clear(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        state = self.bot.guild_manager.get(interaction.guild.id)
        state.queue.clear()
        comps = _queue_list_components([], 0)
        await edit_v2(interaction, comps)

    async def _do_search_select(self, interaction: discord.Interaction, value: str) -> None:
        if interaction.guild is None:
            return
        results = self._search_cache.get(interaction.guild.id, [])
        idx = int(value)
        if idx >= len(results):
            return
        track = results[idx]
        guild_id = interaction.guild.id

        # キューに追加
        await self._add_to_queue(guild_id, [track], interaction.user.id)

        # メッセージ削除
        try:
            await interaction.message.delete()
        except Exception:
            pass

        # 再生開始
        vc: discord.VoiceClient | None = interaction.guild.voice_client
        if vc and not vc.is_playing():
            await self._advance(guild_id)
        else:
            await self.bot.http.request(
                discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=interaction.channel_id),
                json={
                    "flags": 1 << 15,
                    "components": [{
                        "type": 17,
                        "accent_color": 0x57F287,
                        "components": [{"type": 10, "content": f"✅ **{track['title']}** をキューに追加しました。"}],
                    }],
                },
            )


async def setup(bot: "IrohaBot") -> None:
    await bot.add_cog(Music(bot))