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
            help_command=None,
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
            print("⚠️ 以下のCogのロードに失敗しました:")
            for cog_name, error in failed_cogs:
                print(f"  ❌ {cog_name}: {error}")
        else:
            print("✅ すべてのCogのロードに成功しました")

        # --- スラッシュコマンド同期（グローバルのみ）---
        # ※ copy_global_to + guild sync は「重複登録」の原因になるため使わない。
        #   グローバル sync だけで全サーバーに展開される（反映まで最大1時間）。
        #   即時反映が必要な場合は on_guild_join で guild sync を行う。
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
        # Bot が再起動するとメインWS の "gateway session" が新しくなる。
        # しかし古い voice_session_id が Discord サーバー側に残り続けるため、
        # 次の connect() で IDENTIFY を送ると 4017 (Unknown Session) が返る。
        #
        # 【対策】
        # 起動時は VoiceClient が存在しないため voice_state(None) を直送し、
        # VOICE_STATE_UPDATE(channel=None) の受信を待って確認する。
        # ════════════════════════════════════════════════════════
        cleared = 0
        for guild in self.guilds:
            try:
                if guild.me and guild.me.voice:
                    log.info(f"[起動時] 古いVCセッションをクリア: {guild.name} (id={guild.id})")

                    # 1回だけ voice_state(None) を送信
                    await self.ws.voice_state(guild.id, None)

                    # VOICE_STATE_UPDATE(channel=None) の受信を待機（最大5秒）
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
            await asyncio.sleep(2.0)
            log.info("[起動時] セッションクリア後の追加待機（2秒）完了")

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="🎵 いろは Music | /help",
            )
        )

        # --- ギルド管理のみ（コマンド同期は setup_hook のグローバル sync で済んでいる）---
        # ※ ここで tree.sync(guild=guild) を呼ぶと「グローバル + ギルド」の
        #   2重登録になりスラッシュコマンドが2個表示される。絶対に呼ばない。
        for guild in self.guilds:
            try:
                await self.guild_manager.ensure_guild(guild.id)
            except Exception as e:
                log.warning(f"Guild ensure failed ({guild.name}): {e}")

        print(f"✅ 起動完了 / 参加サーバー数: {len(self.guilds)}")

    async def on_guild_join(self, guild: discord.Guild):
        """新規参加ギルドにはギルド sync で即時反映する（重複にはならない）"""
        await self.guild_manager.ensure_guild(guild.id)
        try:
            # 新規参加ギルドのみ guild sync → グローバルより先に表示される
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


# --- 後方互換エイリアス ---
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
