import discord
from discord.ext import commands


# レイテンシー分類関数
def get_latency_status(latency_ms: int):
    if latency_ms <= 50:
        return "超高速", discord.Color.green(), "✅ Botは正常です。"
    elif latency_ms <= 150:
        return "普通", discord.Color.gold(), "✅ Botは正常です。"
    elif latency_ms <= 300:
        return "少し遅い", discord.Color.orange(), "※ 処理負荷が高いかもしれません。"
    else:
        return "遅い", discord.Color.red(), "⚠️ レイテンシーが高いです。再起動を検討してください。"


class Ping(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # hybrid_command にすることでプレフィックス(IM!ping)と
    # スラッシュコマンド(/ping) 両方から呼び出せるようにする
    @commands.hybrid_command(name="ping", description="Botの応答速度を測定します")
    async def ping(self, ctx: commands.Context):
        """Botのレイテンシーを表示する"""
        latency_ms = round(self.bot.latency * 1000)
        status, color, advice = get_latency_status(latency_ms)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=(
                f"**レイテンシー**: `{latency_ms}ms`\n"
                f"**体感速度**: `{status}`\n"
                f"{advice}"
            ),
            color=color,
        )
        # スラッシュ / プレフィックス 両対応
        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.interaction.response.send_message(embed=embed)
        else:
            await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ping(bot))
