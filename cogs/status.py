import discord
from discord.ext import commands, tasks
import asyncio

class Status(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.current_index = 0  # 現在のステータスインデックス
        self.update_status.start()  # 起動時にループ開始

    def cog_unload(self):
        self.update_status.cancel()

    @tasks.loop(seconds=10)  # 10秒ごとに更新
    async def update_status(self):
        await self.bot.wait_until_ready()

        ping = round(self.bot.latency * 1000)
        member_count = sum(guild.member_count for guild in self.bot.guilds)

        # ステータスを順番に定義
        dynamic_presences = [
            {"type": "Playing", "name": "ver 1.1.0 beta", "state": "Powered by Suiten"},
            {"type": "Playing", "name": f"ping: {ping}ms", "state": f"{len(self.bot.users)} users"},
        ]

        # 現在のステータスを取得
        current_presence = dynamic_presences[self.current_index]

        activity = discord.Activity(
            type=discord.ActivityType.playing,
            name=current_presence["name"],
            state=current_presence["state"]
        )
        await self.bot.change_presence(activity=activity, status=discord.Status.online)

        # 次のインデックスへ（最後まで行ったら0に戻る）
        self.current_index = (self.current_index + 1) % len(dynamic_presences)

    @update_status.before_loop
    async def before_status(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Status(bot))