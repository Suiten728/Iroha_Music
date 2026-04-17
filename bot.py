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


class MyBot(commands.Bot):
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
                for filename in files:
                    if filename.endswith(".py") and filename != "__init__.py":
                        rel_path = os.path.relpath(os.path.join(root, filename), ".")
                        cog_name = rel_path.replace(os.sep, ".")[:-3]
                        try:
                            await self.load_extension(cog_name)
                        except Exception as e:
                            failed_cogs.append((cog_name, e))

        # --- ロード結果表示 ---
        if failed_cogs:
            print(f"✅ 以下のFile以外ロードに成功しました - {self.user}")
            for cog_name, error in failed_cogs:
                print(
                    f"❌ ロード失敗 : {cog_name} - {self.user}\n"
                    f"{error}\n"
                )
        else:
            print(f"✅ すべてのFileのロードに成功しました - {self.user}")

        # --- スラッシュコマンド同期 ---
        # グローバルsync（反映まで最大1時間）
        global_synced = await self.tree.sync()
        print(f"✅ グローバルスラッシュコマンド登録数: {len(global_synced)} - {self.user}")

    async def on_ready(self):
        print(f"✅ ログイン完了: {self.user}")
        Config.check_dependencies()
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="🎵 いろは Music | IM!help",
            )
        )

        # --- 起動時: 全ギルドの古いボイスセッションをクリア (4017対策) ---
        # Bot再起動後にDiscordサーバー側に前回のボイスセッションが残ることがある。
        # voice_state(None)後、guild.me.voice が None になるまで待機してから進む。
        for guild in self.guilds:
            try:
                if guild.me and guild.me.voice:
                    log.info(f"古いVCセッションをクリア: {guild.name}")
                    await self.ws.voice_state(guild.id, None)
                    # Discord 側の確認を最大5秒待機
                    for _ in range(50):
                        await asyncio.sleep(0.1)
                        if guild.me is None or guild.me.voice is None:
                            break
            except Exception as e:
                log.warning(f"Voice state clear failed ({guild.name}): {e}")

        # --- 全参加ギルドへ即時sync（開発中は必須）---
        # グローバルsyncは最大1時間かかるため、ギルドごとにコピーして即時反映する
        synced_guilds = 0
        for guild in self.guilds:
            try:
                await self.guild_manager.ensure_guild(guild.id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                synced_guilds += 1
            except Exception as e:
                log.warning(f"Guild sync failed ({guild.name}): {e}")
        print(f"✅ ギルド別スラッシュコマンド即時sync完了: {synced_guilds}サーバー - {self.user}")

    async def on_guild_join(self, guild: discord.Guild):
        await self.guild_manager.ensure_guild(guild.id)
        # 新規参加ギルドにも即時sync
        try:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        except Exception as e:
            log.warning(f"Guild sync failed on join ({guild.name}): {e}")
        print(f"✅ サーバー参加: {guild.name} ({guild.id})")

    async def on_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.CommandNotFound):
            return
        log.error(f"Command error in {ctx.command}: {error}", exc_info=True)


# --- 起動処理 ---
async def main():
    bot = MyBot()
    await bot.start(TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Botを手動で停止しました。")