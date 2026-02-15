import discord
from discord.ext import commands

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

    @commands.command(name="ping", description="Botの応答速度を測定します")
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

async def setup(bot: commands.Bot):
    await bot.add_cog(Ping(bot))