import discord
from discord.ext import commands
from discord import app_commands
import os
from dotenv import load_dotenv

# .envからトークン読み込み
load_dotenv(dotenv_path="ci/.env")
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if TOKEN is None:
    raise ValueError("DISCORD_BOT_TOKEN が見つかりません")

# レイテンシー分類関数
def get_latency_status(latency_ms: int):
    if latency_ms <= 50:
        return "超高速", discord.Color.green(), "✅Botは正常です。"
    elif latency_ms <= 150:
        return "普通", discord.Color.gold(), "✅Botは正常です。"
    elif latency_ms <= 300:
        return "少し遅い", discord.Color.orange(), "※処理負荷が高いかもしれません。"
    else:
        return "遅い", discord.Color.red(), "⚠️ レイテンシーが高いです。再起動を検討してください。"
    
intents = discord.Intents.default()
intents.message_content = True

class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="ping", description="Botの応答速度を測定します")
    async def ping(self, ctx: commands.Context):
        latency_ms = round(self.bot.latency * 1000)
        status, color, advice = get_latency_status(latency_ms)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"**レイテンシー**: `{latency_ms}ms`\n**体感速度**: `{status}`\n{advice}",
            color=color
        )
        if ctx.interaction:
            await ctx.interaction.response.send_message(embed=embed)
        else:
            await ctx.send(embed=embed)

# Botクラス（本体）
class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="P!",
            intents=intents
        )

    async def setup_hook(self):
        await self.add_cog(Ping(self))
        await self.tree.sync()
        print("🔧 setup_hook 完了（Ping Cog 読み込み & スラッシュコマンド同期）")

    async def on_message(self, message):
        await self.process_commands(message)

async def setup(bot: commands.Bot):
    await bot.add_cog(Ping(bot))

# 実行部分
if __name__ == "__main__":
    bot = MyBot()
    bot.run(TOKEN)