import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import asyncio
import logging

from core.guild_manager import GuildManager
from core.logger import setup_logger
from core.config_loader import Config
from data_public.models import Database

# .envからトークン読み込み
load_dotenv()
load_dotenv(dotenv_path="ci/.env")
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if TOKEN is None:
    raise ValueError("DISCORD_BOT_TOKEN が見つかりません")

setup_logger()
log = logging.getLogger("iroha")

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.voice_states = True
intents.members = True


class IrohaBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="IM!",
            intents=intents,
            help_command=None
        )
        self.db: Database | None = None
        self.guild_manager: GuildManager | None = None

    async def setup_hook(self):
        # --- DB初期化 ---
        self.db = Database()
        await self.db.init()
        self.guild_manager = GuildManager(self)

        failed_cogs = []

        # --- Cogをまとめてロード ---
        for folder in ("./cogs",):
            for root, _, files in os.walk(folder):
                for filename in sorted(files):  # 順序を安定させる
                    if filename.endswith(".py") and filename != "__init__.py":
                        rel_path = os.path.relpath(os.path.join(root, filename), ".")
                        cog_name = rel_path.replace(os.sep, ".")[:-3]
                        try:
                            await self.load_extension(cog_name)
                        except Exception as e:
                            failed_cogs.append((cog_name, e))

        # --- ロード結果表示 ---
        if failed_cogs:
            print(f"⚠️ 以下のCogのロードに失敗しました:")
            for cog_name, error in failed_cogs:
                print(f"  ❌ {cog_name}: {error}")
        else:
            print(f"✅ すべてのCogのロードに成功しました")

        # --- スラッシュコマンド同期（グローバル）---
        global_synced = await self.tree.sync()
        print(f"✅ グローバルスラッシュコマンド登録数: {len(global_synced)}")

    async def on_ready(self):
        print(f"✅ ログイン完了: {self.user}")
        Config.check_dependencies()

        # ════════════════════════════════════════════════════════
        # 起動時: 全ギルドの古いボイスセッションをクリア (4017対策)
        # ════════════════════════════════════════════════════════
        #
        # 【4017エラー（Unknown Session）の根本原因】
        #
        # Discord のボイス接続は以下のフローで行われる:
        #   1. メインWS → opcode 4 (voice_state) 送信
        #   2. Discord → VOICE_STATE_UPDATE で session_id を返却
        #   3. Discord → VOICE_SERVER_UPDATE で token/endpoint を返却
        #   4. ボイスWS 接続 → IDENTIFY (opcode 0) 送信
        #      ※ IDENTIFY の payload に session_id を含む
        #   5. Discord が session_id を検証 → 有効なら接続成立
        #
        # Bot が再起動するとメインWS の "gateway session" が新しくなる。
        # しかし Bot が以前ボイスチャンネルに居た場合、Discord サーバー側には
        # 古い voice_session_id が残り続ける。
        # この状態で接続すると古い session_id が IDENTIFY に使われ
        # 4017 (Unknown Session) が返されてしまう。
        #
        # 【対策: VoiceClient.disconnect を使わず voice_state(None) だけ送る理由】
        #
        # 起動時は VoiceClient オブジェクト自体が存在しない
        # （Bot 再起動で discord.py の内部状態がリセットされているため）。
        # VoiceClient.disconnect() は VoiceClient が存在する前提の API のため
        # 起動時には使えない。
        # したがって直接 bot.ws.voice_state(guild_id, None) を送り、
        # VOICE_STATE_UPDATE(channel=None) の受信を待つ方式を採用する。
        #
        # ※ VoiceClient が存在する場合（切断なしの再接続等）は
        #   Music Cog の _reset_voice_session() で disconnect() を使用する。
        # ════════════════════════════════════════════════════════
        cleared = 0
        for guild in self.guilds:
            try:
                if guild.me and guild.me.voice:
                    log.info(f"[起動時] 古いVCセッションをクリア: {guild.name} (id={guild.id})")

                    # 1回だけ voice_state(None) を送信
                    # ※ 複数回送ると Discord 側の状態が不定になるため厳密に1回
                    await self.ws.voice_state(guild.id, None)

                    # VOICE_STATE_UPDATE(channel=None) の受信を待機（最大5秒）
                    # guild.me.voice が None になれば Discord 側のセッション消去を確認できる
                    cleared_flag = False
                    for _ in range(50):
                        await asyncio.sleep(0.1)
                        if guild.me is None or guild.me.voice is None:
                            cleared_flag = True
                            break

                    if cleared_flag:
                        log.info(f"[起動時] セッションクリア確認: {guild.name}")
                    else:
                        log.warning(
                            f"[起動時] セッションクリア確認タイムアウト: {guild.name} "
                            f"→ 強行続行（guild.me.voice={guild.me.voice!r}）"
                        )
                    cleared += 1

            except Exception as e:
                log.warning(f"[起動時] Voice state clear 失敗 ({guild.name}): {e}")

        if cleared:
            print(f"🔄 古いボイスセッションをクリア: {cleared}ギルド")
            # Discord 側のセッション記録削除が全ノードに伝播するのを待つ
            # この待機がないと次の connect() 呼び出しで 4017 が発生することがある
            await asyncio.sleep(2.0)
            log.info("[起動時] セッションクリア後の追加待機（2秒）完了")

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="🎵 いろは Music | IM!help",
            )
        )

        # --- 全参加ギルドへ即時sync ---
        synced_guilds = 0
        for guild in self.guilds:
            try:
                await self.guild_manager.ensure_guild(guild.id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                synced_guilds += 1
            except Exception as e:
                log.warning(f"Guild sync failed ({guild.name}): {e}")
        print(f"✅ ギルド別スラッシュコマンド即時sync完了: {synced_guilds}サーバー")

    async def on_guild_join(self, guild: discord.Guild):
        await self.guild_manager.ensure_guild(guild.id)
        try:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        except Exception as e:
            log.warning(f"Guild sync failed on join ({guild.name}): {e}")
        print(f"✅ サーバー参加: {guild.name} ({guild.id})")

    async def close(self):
        """Bot終了時にDBを閉じる"""
        if self.db:
            await self.db.close()
        await super().close()

    async def on_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.CommandNotFound):
            return
        log.error(f"Command error in {ctx.command}: {error}", exc_info=True)


# --- 後方互換エイリアス（TYPE_CHECKING で IrohaBot と参照される） ---
MyBot = IrohaBot


# --- 起動処理 ---
async def main():
    bot = IrohaBot()
    try:
        await bot.start(TOKEN)
    finally:
        await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Botを手動で停止しました。")
