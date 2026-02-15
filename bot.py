import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import asyncio

# .envからトークン読み込み
load_dotenv(dotenv_path="ci/.env")
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if TOKEN is None:
    raise ValueError("DISCORD_BOT_TOKEN が見つかりません")

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True 

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="IM!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
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
        synced = await self.tree.sync()
        print(f"✅ スラッシュコマンド登録数: {len(synced)} - {self.user}")

    async def on_ready(self):
        print(f"✅ ログイン完了: {self.user}")

# --- 起動処理 ---
async def main():
    bot = MyBot()
    await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Botを手動で停止しました。")	