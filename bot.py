import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import asyncio
import logging

from core.guild_manager import GuildManager
from core.logger import setup_logger
from core.config_loader import Config
from data.models import Database

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

        # --- 起動時: 全ギルドの古いボイスセッションをクリア (4017対策) ---
        #
        # 【4017エラーの根本原因】
        # Discord の WebSocket セッションには "voice session_id" が紐付く。
        # Botを再起動すると WebSocket セッション自体が新しくなるため
        # 古い session_id はサーバー側で無効になる。
        # この状態で connect() を呼ぶと内部的に同じ無効な session_id で
        # 再接続しようとするため 4017 (Unknown Session) が返り続ける。
        #
        # 【対策】
        # voice_state(guild_id, None) でサーバー側のボイスセッション記録を消去し、
        # VOICE_STATE_UPDATE が届いて guild.me.voice が None になるまで待機する。
        # これにより次の connect() が新しい session_id を確実に取得できる。
        cleared = 0
        for guild in self.guilds:
            try:
                if guild.me and guild.me.voice:
                    log.info(f"[起動時] 古いVCセッションをクリア: {guild.name}")
                    await self.ws.voice_state(guild.id, None)
                    # VOICE_STATE_UPDATE の到着を最大3秒待機
                    for _ in range(30):
                        await asyncio.sleep(0.1)
                        if guild.me is None or guild.me.voice is None:
                            break
                    cleared += 1
            except Exception as e:
                log.warning(f"Voice state clear failed ({guild.name}): {e}")

        if cleared:
            print(f"🔄 古いボイスセッションをクリア: {cleared}ギルド")
            # Discord側のセッション記録削除が全ギルドで完全に反映されるのを待つ
            await asyncio.sleep(1.5)

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
