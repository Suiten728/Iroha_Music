"""
cogs/music.py — 再生・キュー管理・基本コントロール
LayoutView / Component v2 を使用
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from utils.audio_engine import YTDLSource, make_ffmpeg_source, PRESETS

if TYPE_CHECKING:
    from bot import IrohaBot

log = logging.getLogger("iroha.music")


# ════════════════════════════════════════════════════════════════
# ヘルパー関数
# ════════════════════════════════════════════════════════════════

async def _ack(ctx: commands.Context) -> None:
    """
    hybrid_command がスラッシュとして呼ばれた場合、
    Interaction を必ず defer して3秒タイムアウトを防ぐ。
    プレフィックスコマンドの場合は何もしない。
    """
    if ctx.interaction and not ctx.interaction.response.is_done():
        await ctx.interaction.response.defer()


async def _post_v2(bot, channel_id: int, components: list[dict]) -> None:
    """IS_COMPONENTS_V2 フラグ付きでチャンネルにHTTP直送する"""
    await bot.http.request(
        discord.http.Route(
            "POST", "/channels/{channel_id}/messages",
            channel_id=channel_id,
        ),
        json={"flags": 1 << 15, "components": components},
    )


async def _edit_v2(bot, channel_id: int, message_id: int, components: list[dict]) -> None:
    """IS_COMPONENTS_V2 フラグ付きでメッセージをHTTP直接編集する"""
    await bot.http.request(
        discord.http.Route(
            "PATCH",
            "/channels/{channel_id}/messages/{message_id}",
            channel_id=channel_id,
            message_id=message_id,
        ),
        json={"flags": 1 << 15, "components": components},
    )


# ════════════════════════════════════════════════════════════════
# Component v2 JSON ビルダー
# ════════════════════════════════════════════════════════════════

def _now_playing_components(
    track: dict, volume: int, loop_mode: str, queue_len: int
) -> list[dict]:
    dur = YTDLSource.format_duration(track.get("duration", 0))
    loop_label = {"none": "ループなし", "one": "1曲ループ", "all": "全体ループ"}.get(loop_mode, "")
    loop_icon  = {"none": "🔁", "one": "🔂", "all": "🔁"}.get(loop_mode, "🔁")

    return [
        {
            "type": 17,
            "accent_color": 0x5865F2,
            "components": [
                {"type": 10, "content": f"## 🎵 Now Playing\n**{track['title']}**"},
                {"type": 14, "spacing": 1},
                {
                    "type": 9,
                    "components": [
                        {"type": 10, "content": (
                            f"⏱️ {dur}　🔊 音量 {volume}%\n"
                            f"{loop_icon} {loop_label}　📋 キュー残り {queue_len}曲"
                        )}
                    ],
                    "accessory": {
                        "type": 2, "style": 5,
                        "label": "YouTube",
                        "url": track.get("webpage_url") or "https://youtube.com",
                    },
                },
                {"type": 14, "spacing": 2},
                {
                    "type": 1,
                    "components": [
                        {"type": 2, "style": 4, "label": "⏭ スキップ",   "custom_id": "music:skip"},
                        {"type": 2, "style": 1, "label": "⏸ 一時停止",   "custom_id": "music:pause"},
                        {"type": 2, "style": 1, "label": "▶ 再開",       "custom_id": "music:resume"},
                        {"type": 2, "style": 2, "label": "⏹ 停止",       "custom_id": "music:stop"},
                    ],
                },
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 3,
                            "custom_id": "music:loop_select",
                            "placeholder": f"ループ設定: {loop_label}",
                            "options": [
                                {"label": "🔁 ループなし", "value": "none"},
                                {"label": "🔂 1曲ループ",  "value": "one"},
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


def _queue_components(queue: list, page: int = 0) -> list[dict]:
    page_size   = 8
    total_pages = max(1, (len(queue) + page_size - 1) // page_size)
    page        = max(0, min(page, total_pages - 1))
    start       = page * page_size
    page_items  = queue[start : start + page_size]

    lines = []
    for i, track in enumerate(page_items, start=start + 1):
        dur = YTDLSource.format_duration(track.get("duration", 0))
        lines.append(f"`{i:02d}.` **{track['title'][:50]}** `{dur}`")

    content = "\n".join(lines) if lines else "キューは空です"

    nav_buttons = []
    if page > 0:
        nav_buttons.append({
            "type": 2, "style": 1,
            "label": "◀ 前へ",
            "custom_id": f"music:queue_page:{page - 1}",
        })
    if page < total_pages - 1:
        nav_buttons.append({
            "type": 2, "style": 1,
            "label": "次へ ▶",
            "custom_id": f"music:queue_page:{page + 1}",
        })
    nav_buttons.append({"type": 2, "style": 3, "label": "🔀 シャッフル", "custom_id": "music:shuffle"})
    nav_buttons.append({"type": 2, "style": 4, "label": "🗑 全クリア",   "custom_id": "music:queue_clear"})

    comps: list[dict] = [
        {
            "type": 17,
            "accent_color": 0xFEE75C,
            "components": [
                {"type": 10, "content": (
                    f"## 📋 キュー一覧 ({len(queue)}曲) — "
                    f"{page + 1}/{total_pages}ページ"
                )},
                {"type": 14, "spacing": 1},
                {"type": 10, "content": content},
                {"type": 14, "spacing": 1},
                {"type": 1, "components": nav_buttons},
            ],
        }
    ]
    return comps


def _simple_components(text: str, accent: int = 0x5865F2) -> list[dict]:
    """シンプルなテキスト1行コンテナ"""
    return [
        {
            "type": 17,
            "accent_color": accent,
            "components": [{"type": 10, "content": text}],
        }
    ]


# ════════════════════════════════════════════════════════════════
# Persistent View（ボタン / セレクトのコールバック受け取り）
# ════════════════════════════════════════════════════════════════

class MusicControlView(discord.ui.View):
    """
    add_view 登録用 Persistent View。
    NowPlayingUI・キューUI・検索UIのすべてのインタラクションをここで受け取る。
    queue_page など動的 custom_id は on_interaction で処理する。
    """

    def __init__(self, cog: "Music") -> None:
        super().__init__(timeout=None)
        self._cog = cog

    # ── NowPlaying ボタン ────────────────────────────────────────

    @discord.ui.button(custom_id="music:skip", label="⏭ スキップ", style=discord.ButtonStyle.danger)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        guild = interaction.guild
        if guild and guild.voice_client and guild.voice_client.is_playing():
            guild.voice_client.stop()

    @discord.ui.button(custom_id="music:pause", label="⏸ 一時停止", style=discord.ButtonStyle.primary)
    async def pause_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        guild = interaction.guild
        if guild and guild.voice_client:
            vc = guild.voice_client
            if vc.is_playing():
                vc.pause()

    @discord.ui.button(custom_id="music:resume", label="▶ 再開", style=discord.ButtonStyle.primary)
    async def resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        guild = interaction.guild
        if guild and guild.voice_client and guild.voice_client.is_paused():
            guild.voice_client.resume()

    @discord.ui.button(custom_id="music:stop", label="⏹ 停止", style=discord.ButtonStyle.secondary)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        guild = interaction.guild
        if guild is None:
            return
        state = self._cog.bot.guild_manager.get(guild.id)
        state.queue.clear()
        state.current = None
        if guild.voice_client:
            guild.voice_client.stop()

    @discord.ui.select(
        custom_id="music:loop_select",
        options=[
            discord.SelectOption(label="🔁 ループなし", value="none"),
            discord.SelectOption(label="🔂 1曲ループ",  value="one"),
            discord.SelectOption(label="🔁 全体ループ", value="all"),
        ],
    )
    async def loop_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        await interaction.response.defer()
        if interaction.guild:
            state = self._cog.bot.guild_manager.get(interaction.guild.id)
            state.loop_mode = select.values[0]

    # ── キューUI ボタン ──────────────────────────────────────────

    @discord.ui.button(custom_id="music:shuffle", label="🔀 シャッフル", style=discord.ButtonStyle.success)
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        if interaction.guild is None:
            return
        state = self._cog.bot.guild_manager.get(interaction.guild.id)
        random.shuffle(state.queue)
        comps = _queue_components(state.queue, 0)
        await _edit_v2(self._cog.bot, interaction.channel_id, interaction.message.id, comps)

    @discord.ui.button(custom_id="music:queue_clear", label="🗑 全クリア", style=discord.ButtonStyle.danger)
    async def clear_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        if interaction.guild is None:
            return
        state = self._cog.bot.guild_manager.get(interaction.guild.id)
        state.queue.clear()
        comps = _queue_components([], 0)
        await _edit_v2(self._cog.bot, interaction.channel_id, interaction.message.id, comps)

    # ── 検索 セレクト ────────────────────────────────────────────

    @discord.ui.select(
        custom_id="music:search_select",
        options=[discord.SelectOption(label="placeholder", value="0")],
    )
    async def search_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        await interaction.response.defer()
        if interaction.guild is None:
            return
        guild_id = interaction.guild.id
        results  = self._cog._search_cache.get(guild_id, [])
        try:
            idx = int(select.values[0])
        except (ValueError, IndexError):
            return
        if idx >= len(results):
            return

        track = results[idx]
        await self._cog._add_to_queue(guild_id, [track], interaction.user.id)

        try:
            await interaction.message.delete()
        except Exception:
            pass

        vc: discord.VoiceClient | None = interaction.guild.voice_client
        if vc and not vc.is_playing():
            await self._cog._advance(guild_id)
        else:
            await _post_v2(
                self._cog.bot,
                interaction.channel_id,
                _simple_components(f"✅ **{track['title']}** をキューに追加しました。", 0x57F287),
            )

    @discord.ui.button(custom_id="music:search_cancel", label="キャンセル", style=discord.ButtonStyle.secondary)
    async def search_cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            await interaction.message.delete()
        except Exception:
            pass
        if not interaction.response.is_done():
            await interaction.response.defer()

    # ── 動的 custom_id（queue_page）は Music Cog の on_interaction で処理 ────
    # NOTE: discord.ui.View は commands.Cog.listener() デコレータを解釈しない。
    #       @commands.Cog.listener() は commands.Cog サブクラスのメソッドに
    #       のみ有効であるため、View 内に置いても一切呼び出されない（サイレント失敗）。
    #       そのため on_interaction は Music Cog 側に定義する。


# ════════════════════════════════════════════════════════════════
# Music Cog
# ════════════════════════════════════════════════════════════════

class Music(commands.Cog):
    def __init__(self, bot: "IrohaBot") -> None:
        self.bot = bot
        self._search_cache: dict[int, list[dict]] = {}

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self.bot.add_view(MusicControlView(self))
        log.info("MusicControlView registered (persistent).")

    # ── 動的 custom_id（queue_page）をここで処理 ────────────────────────
    # MusicControlView は discord.ui.View を継承しており Cog.listener を持てない。
    # queue_page:{n} のような動的な custom_id は Persistent View の
    # @discord.ui.button では登録できないため、Cog 側の on_interaction で処理する。

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """music:queue_page:{n} のような動的 custom_id をここで処理する"""
        if interaction.type != discord.InteractionType.component:
            return
        custom_id: str = interaction.data.get("custom_id", "")
        if not custom_id.startswith("music:queue_page:"):
            return
        try:
            page = int(custom_id.split(":")[-1])
        except ValueError:
            await interaction.response.defer()
            return

        if interaction.guild is None:
            await interaction.response.defer()
            return

        state = self.bot.guild_manager.get(interaction.guild.id)
        comps = _queue_components(state.queue, page)
        await _edit_v2(self.bot, interaction.channel_id, interaction.message.id, comps)
        await interaction.response.defer()

    # ── ボイス接続ヘルパー ───────────────────────────────────────

    async def _reset_voice_session(self, guild: discord.Guild) -> None:
        """
        Discord側のボイスセッションを完全リセットする。

        【4017エラーの根本原因と対策】
        discord.py の VoiceClient は内部に session_id を保持している。
        Botが再起動すると WebSocket セッションが新しくなるため
        古い session_id はDiscordサーバー側で無効(Unknown)になる。
        この状態でそのまま connect() しようとすると
        Discordは 4017 (Unknown Session) を返し続ける。

        対策:
        1. discord.py 内部の VoiceClient を force=True で破棄する
        2. メインWSに voice_state(None) を送りDiscord側のセッション記録を消去する
        3. VOICE_STATE_UPDATE イベントが届いて guild.me.voice が None になるまで
           待機する（これが None になって初めてDiscord側でセッションが消えた状態）
        4. その後 connect() することで新しい session_id が正常に発行される
        """
        # Step 1: discord.py 内部オブジェクトを破棄
        vc = guild.voice_client
        if vc is not None:
            try:
                await vc.disconnect(force=True)
            except Exception as e:
                log.debug(f"[Guild {guild.id}] VoiceClient.disconnect(force=True): {e}")

        # Step 2: メインWSに「このギルドのVCから離脱」を送信
        try:
            await self.bot.ws.voice_state(guild.id, None)
            log.info(f"[Guild {guild.id}] voice_state(None) 送信完了")
        except Exception as e:
            log.warning(f"[Guild {guild.id}] voice_state(None) 送信失敗: {e}")
            return

        # Step 3: VOICE_STATE_UPDATE が届くまで待機（最大5秒）
        # guild.me.voice が None になるまで待つことでサーバー側のセッション消去を確認
        for i in range(50):
            await asyncio.sleep(0.1)
            if guild.me is None or guild.me.voice is None:
                log.info(f"[Guild {guild.id}] セッションクリア確認 ({(i+1)*0.1:.1f}秒)")
                return
        log.warning(f"[Guild {guild.id}] セッションクリア待機タイムアウト（5秒）→ 強行続行")

    async def _ensure_voice(self, ctx: commands.Context) -> discord.VoiceClient | None:
        """
        ユーザーのVCに接続し VoiceClient を返す。
        4017エラー対策として独自リトライループを実装。

        reconnect=False にして discord.py 内部の無限リトライを停止し、
        アプリ側でセッションリセット → 再接続を制御する。
        """
        if ctx.author.voice is None:
            await ctx.send("❌ まずボイスチャンネルに参加してください。")
            return None

        guild     = ctx.guild
        guild_id  = guild.id
        target_ch = ctx.author.voice.channel
        vc: discord.VoiceClient | None = ctx.voice_client

        # ── すでに正常接続済み ──────────────────────────────────
        if vc is not None and vc.is_connected():
            if vc.channel == target_ch:
                await self.bot.guild_manager.ensure_guild(guild_id)
                state = self.bot.guild_manager.get(guild_id)
                state.text_channel_id = ctx.channel.id
                return vc
            else:
                # 別チャンネルへ移動
                try:
                    await vc.move_to(target_ch)
                    await self.bot.guild_manager.ensure_guild(guild_id)
                    state = self.bot.guild_manager.get(guild_id)
                    state.text_channel_id = ctx.channel.id
                    return vc
                except Exception as e:
                    log.warning(f"[Guild {guild_id}] move_to失敗: {e}")
                    # 移動失敗時はいったん切断してから再接続へ

        # ── 未接続 or 切断状態 → リセット＆再接続ループ ────────────
        # discord.py の reconnect=True は 4017 でも同じ無効な session_id で
        # リトライし続けるため、アプリ側でリセットを挟んでリトライする。
        MAX_ATTEMPTS = 3
        last_error: Exception | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            log.info(f"[Guild {guild_id}] VC接続試行 {attempt}/{MAX_ATTEMPTS}")

            # セッションを完全リセット（古い session_id を消去）
            await self._reset_voice_session(guild)

            # リセット後に少し待機して Discord 側の反映を確実にする
            await asyncio.sleep(0.5)

            try:
                # reconnect=False: discord.py 内部リトライを無効にして
                #                  アプリ側でリトライを制御する
                vc = await target_ch.connect(timeout=20.0, reconnect=False)
                log.info(f"[Guild {guild_id}] VC接続成功（{attempt}回目）")
                break

            except discord.errors.ConnectionClosed as e:
                last_error = e
                if e.code == 4017:
                    log.warning(
                        f"[Guild {guild_id}] 4017 (Unknown Session): "
                        f"セッション無効 → リセット後に再試行 ({attempt}/{MAX_ATTEMPTS})"
                    )
                    # 指数バックオフ: 2秒, 4秒, 6秒
                    await asyncio.sleep(2.0 * attempt)
                    continue
                elif e.code == 4006:
                    log.warning(
                        f"[Guild {guild_id}] 4006 (Session No Longer Valid): "
                        f"セッション期限切れ → リセット後に再試行 ({attempt}/{MAX_ATTEMPTS})"
                    )
                    await asyncio.sleep(2.0 * attempt)
                    continue
                else:
                    log.error(f"[Guild {guild_id}] VC接続失敗 code={e.code}: {e}")
                    await ctx.send(f"❌ ボイスチャンネルへの接続に失敗しました。(code={e.code})")
                    return None

            except asyncio.TimeoutError:
                last_error = asyncio.TimeoutError()
                log.warning(f"[Guild {guild_id}] VC接続タイムアウト ({attempt}回目)")
                await asyncio.sleep(2.0 * attempt)
                continue

            except Exception as e:
                last_error = e
                log.error(f"[Guild {guild_id}] VC接続失敗: {type(e).__name__}: {e}")
                await ctx.send("❌ ボイスチャンネルへの接続に失敗しました。")
                return None

        else:
            # MAX_ATTEMPTS 回全て失敗
            log.error(f"[Guild {guild_id}] VC接続 {MAX_ATTEMPTS}回全て失敗: {last_error}")
            await ctx.send(
                f"❌ ボイスチャンネルへの接続を {MAX_ATTEMPTS} 回試みましたが失敗しました。\n"
                "しばらく待ってから再度お試しください。"
            )
            return None

        await self.bot.guild_manager.ensure_guild(guild_id)
        state = self.bot.guild_manager.get(guild_id)
        state.text_channel_id = ctx.channel.id
        return vc

    # ── キュー追加 ───────────────────────────────────────────────

    async def _add_to_queue(self, guild_id: int, tracks: list[dict], requester_id: int) -> None:
        state    = self.bot.guild_manager.get(guild_id)
        settings = await self.bot.guild_manager.get_settings(guild_id)
        max_q    = settings.get("max_queue", 200)
        for track in tracks:
            if len(state.queue) >= max_q:
                break
            track["requester_id"] = requester_id
            state.queue.append(track)

    # ── 再生エンジン ─────────────────────────────────────────────

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
            pass  # キューに再追加しない（同じ曲を再再生）
        elif state.loop_mode == "all" and state.current:
            state.queue.append(state.current)

        if not state.queue:
            state.current = None
            await self._schedule_auto_leave(guild_id, guild)
            return

        if state.shuffle:
            random.shuffle(state.queue)

        # vc が None（接続前に切断等）の場合はキューを保持したまま終了
        if vc is None or not vc.is_connected():
            log.warning(f"[Guild {guild_id}] _advance: VoiceClient が None のためスキップ")
            return

        next_track     = state.queue.pop(0)
        state.current  = next_track
        await self._play_track(guild_id, vc, next_track)

    async def _play_track(
        self, guild_id: int, vc: discord.VoiceClient | None, track: dict
    ) -> None:
        if vc is None or not vc.is_connected():
            log.error(f"[Guild {guild_id}] _play_track: VoiceClient が None または未接続")
            return
        state     = self.bot.guild_manager.get(guild_id)
        audio_cfg = await self.bot.guild_manager.get_audio_settings(guild_id)
        eq_bands  = json.loads(audio_cfg.get("eq_bands", "{}"))

        # ストリームURLは期限付きのため再生直前に再取得
        webpage_url = track.get("webpage_url", "")
        stream_url  = await YTDLSource.get_stream_url(webpage_url)
        if not stream_url:
            log.error(f"[Guild {guild_id}] ストリームURL取得失敗（メン限・削除済み等）: {webpage_url}")
            ch_id = state.text_channel_id
            if ch_id:
                try:
                    await _post_v2(
                        self.bot, ch_id,
                        _simple_components(
                            f"⚠️ **{track['title']}** は再生できませんでした。"
                            "（メンバー限定・削除済み・地域制限等）次の曲へスキップします。",
                            0xFEE75C,
                        ),
                    )
                except Exception:
                    pass
            asyncio.create_task(self._advance(guild_id))
            return

        try:
            source = make_ffmpeg_source(
                stream_url,
                volume=state.volume,
                bass_boost=audio_cfg.get("bass_boost", 0),
                surround=bool(audio_cfg.get("surround", 0)),
                reverb_level=0.0,
                eq_bands=eq_bands if eq_bands else None,
            )
        except discord.ClientException as e:
            log.error(f"[Guild {guild_id}] FFmpeg起動失敗: {e}")
            ch_id = state.text_channel_id
            if ch_id:
                await _post_v2(
                    self.bot, ch_id,
                    _simple_components(
                        "## ❌ ffmpeg が見つかりません\n"
                        "音楽再生には `ffmpeg` が必要です。\n"
                        "```\nsudo apt install ffmpeg\n```",
                        0xED4245,
                    ),
                )
            return

        vc.play(source, after=lambda e: self._after_track(guild_id, e))
        state.is_playing = True
        state.skip_votes.clear()

        await self._record_stat(guild_id, track)
        await self._send_now_playing(guild_id, state, track, vc)

    async def _send_now_playing(
        self, guild_id: int, state, track: dict, vc: discord.VoiceClient
    ) -> None:
        settings = await self.bot.guild_manager.get_settings(guild_id)
        ch_id    = settings.get("music_channel_id") or state.text_channel_id
        if not ch_id:
            log.warning(f"[Guild {guild_id}] NowPlaying送信先チャンネルが未設定")
            return

        channel = self.bot.get_channel(ch_id)
        if not channel or not isinstance(channel, (discord.TextChannel, discord.Thread)):
            log.warning(f"[Guild {guild_id}] チャンネルが見つかりません (id={ch_id})")
            return

        comps = _now_playing_components(
            track,
            int(state.volume * 100),
            state.loop_mode,
            len(state.queue),
        )
        try:
            await _post_v2(self.bot, ch_id, comps)
            log.debug(f"[Guild {guild_id}] NowPlaying sent → #{channel.name}")
        except Exception as e:
            log.warning(f"[Guild {guild_id}] NowPlaying送信失敗: {e}")

    async def _record_stat(self, guild_id: int, track: dict) -> None:
        try:
            await self.bot.db.execute(
                """INSERT INTO music_stats(guild_id, user_id, title, url, duration)
                   VALUES(?, ?, ?, ?, ?)""",
                (
                    guild_id,
                    track.get("requester_id", 0),
                    track["title"],
                    track.get("webpage_url", ""),
                    track.get("duration", 0),
                ),
            )
            await self.bot.db.commit()
        except Exception as e:
            log.warning(f"Failed to record stat: {e}")

    async def _schedule_auto_leave(self, guild_id: int, guild: discord.Guild) -> None:
        state    = self.bot.guild_manager.get(guild_id)
        settings = await self.bot.guild_manager.get_settings(guild_id)
        delay    = settings.get("auto_leave_sec", 300)

        async def _leave() -> None:
            await asyncio.sleep(delay)
            vc = guild.voice_client
            if vc and vc.is_connected() and not vc.is_playing():
                await vc.disconnect()
                log.info(f"[Guild {guild_id}] {delay}秒無音のため自動切断")

        if state.auto_leave_task:
            state.auto_leave_task.cancel()
        state.auto_leave_task = asyncio.create_task(_leave())

    # ════════════════════════════════════════════════════════════
    # コマンド定義
    # ════════════════════════════════════════════════════════════

    @commands.hybrid_command(name="play", aliases=["p"])
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """URLまたは検索ワードで音楽を再生する"""
        await _ack(ctx)
        try:
            vc = await self._ensure_voice(ctx)
            if vc is None:
                return

            async with ctx.typing():
                results = await YTDLSource.search(query)

            if not results:
                await ctx.send("❌ 検索結果が見つかりませんでした。")
                return

            if YTDLSource._is_url(query):
                track = results[0]
                await self._add_to_queue(ctx.guild.id, [track], ctx.author.id)
                if not vc.is_playing():
                    await self._advance(ctx.guild.id)
                else:
                    await _post_v2(
                        self.bot, ctx.channel.id,
                        _simple_components(f"✅ **{track['title']}** をキューに追加しました。", 0x57F287),
                    )
            else:
                self._search_cache[ctx.guild.id] = results
                await _post_v2(
                    self.bot, ctx.channel.id,
                    _search_result_components(results[:5], query),
                )
        except Exception as e:
            import traceback
            traceback.print_exc()
            await ctx.send(f"```\n{type(e).__name__}: {e}\n```")

    @commands.hybrid_command(name="search", aliases=["s"])
    async def search(self, ctx: commands.Context, *, query: str) -> None:
        """キーワードで検索して選択画面を表示する"""
        await self.play(ctx, query=query)

    @commands.hybrid_command(name="playlist", aliases=["pl"])
    async def playlist(self, ctx: commands.Context, url: str) -> None:
        """プレイリストURLを丸ごと追加する"""
        await _ack(ctx)
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
            vc_now = ctx.voice_client
            if vc_now and not vc_now.is_playing():
                await self._advance(ctx.guild.id)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await ctx.send(f"```\n{type(e).__name__}: {e}\n```")

    @commands.hybrid_command(name="queue", aliases=["q"])
    async def queue_cmd(self, ctx: commands.Context) -> None:
        """キュー一覧を表示する"""
        await _ack(ctx)
        state = self.bot.guild_manager.get(ctx.guild.id)
        comps = _queue_components(state.queue, 0)
        await _post_v2(self.bot, ctx.channel.id, comps)

    @commands.hybrid_command(name="nowplaying", aliases=["np", "now"])
    async def nowplaying(self, ctx: commands.Context) -> None:
        """現在再生中の曲を表示する"""
        await _ack(ctx)
        state = self.bot.guild_manager.get(ctx.guild.id)
        if not state.current:
            await ctx.send("❌ 現在再生中の曲はありません。")
            return
        comps = _now_playing_components(
            state.current, int(state.volume * 100), state.loop_mode, len(state.queue)
        )
        await _post_v2(self.bot, ctx.channel.id, comps)

    @commands.hybrid_command(name="pause")
    async def pause(self, ctx: commands.Context) -> None:
        """再生を一時停止する"""
        await _ack(ctx)
        vc = ctx.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await ctx.send("⏸ 一時停止しました。")
        else:
            await ctx.send("❌ 再生中の曲がありません。")

    @commands.hybrid_command(name="resume")
    async def resume(self, ctx: commands.Context) -> None:
        """一時停止を解除する"""
        await _ack(ctx)
        vc = ctx.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await ctx.send("▶ 再開しました。")
        else:
            await ctx.send("❌ 一時停止中の曲がありません。")

    @commands.hybrid_command(name="skip")
    async def skip(self, ctx: commands.Context) -> None:
        """曲をスキップする（投票スキップ）"""
        await _ack(ctx)
        state = self.bot.guild_manager.get(ctx.guild.id)
        vc    = ctx.voice_client
        if not vc or not vc.is_playing():
            await ctx.send("❌ 再生中の曲がありません。")
            return
        state.skip_votes.add(ctx.author.id)
        members = [m for m in vc.channel.members if not m.bot]
        needed  = max(1, len(members) // 2)
        votes   = len(state.skip_votes)
        if votes >= needed:
            vc.stop()
            await ctx.send(f"⏭ スキップしました。({votes}/{needed} 票)")
        else:
            await ctx.send(f"🗳 スキップ投票: {votes}/{needed} 票")

    @commands.hybrid_command(name="stop")
    async def stop(self, ctx: commands.Context) -> None:
        """再生を停止してキューをクリアする"""
        await _ack(ctx)
        state = self.bot.guild_manager.get(ctx.guild.id)
        state.queue.clear()
        state.current = None
        if ctx.voice_client:
            ctx.voice_client.stop()
        await ctx.send("⏹ 停止しました。")

    @commands.hybrid_command(name="volume", aliases=["vol"])
    async def volume(self, ctx: commands.Context, vol: int) -> None:
        """音量を変更する (1-150)"""
        await _ack(ctx)
        if not 1 <= vol <= 150:
            await ctx.send("❌ 音量は 1〜150 で指定してください。")
            return
        state = self.bot.guild_manager.get(ctx.guild.id)
        state.volume = vol / 100
        if ctx.voice_client and ctx.voice_client.source:
            ctx.voice_client.source.volume = state.volume
        await ctx.send(f"🔊 音量を **{vol}%** に設定しました。")

    @commands.hybrid_command(name="loop")
    async def loop(self, ctx: commands.Context, mode: str = "one") -> None:
        """ループモード設定 (none / one / all)"""
        await _ack(ctx)
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
        """シャッフル ON/OFF を切り替える"""
        await _ack(ctx)
        state = self.bot.guild_manager.get(ctx.guild.id)
        state.shuffle = not state.shuffle
        await ctx.send(f"🔀 シャッフルを **{'ON' if state.shuffle else 'OFF'}** にしました。")

    @commands.hybrid_command(name="leave", aliases=["dc"])
    async def leave(self, ctx: commands.Context) -> None:
        """ボイスチャンネルから切断する"""
        await _ack(ctx)
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("👋 切断しました。")
        else:
            await ctx.send("❌ ボイスチャンネルに接続していません。")


async def setup(bot: "IrohaBot") -> None:
    await bot.add_cog(Music(bot))
