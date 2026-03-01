"""
いろは Music System — bot.py
次世代型AI診断 × 高度音響処理対応 Discord音楽Bot
"""

import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from core.config_loader import Config
from core.guild_manager import GuildManager
from core.logger import setup_logger
from data.models import Database

load_dotenv()
setup_logger()
log = logging.getLogger("iroha")

COGS = [
    "cogs.music",
    "cogs.queue_cog",
    "cogs.ai_diagnosis",
    "cogs.audio_effects",
    "cogs.statistics",
    "cogs.party",
    "cogs.sensitive_filter",
]


class IrohaBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.guilds = True
        intents.members = True

        super().__init__(
            command_prefix=Config.PREFIX,
            intents=intents,
            help_command=None,
        )
        self.db: Database | None = None
        self.guild_manager: GuildManager | None = None

    async def setup_hook(self) -> None:
        self.db = Database()
        await self.db.init()
        self.guild_manager = GuildManager(self)

        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info(f"Loaded cog: {cog}")
            except Exception as e:
                log.error(f"Failed to load cog {cog}: {e}", exc_info=True)

        await self.tree.sync()
        log.info("Slash commands synced.")

    async def on_ready(self) -> None:
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="🎵 いろは Music | /help",
            )
        )

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self.guild_manager.ensure_guild(guild.id)
        log.info(f"Joined guild: {guild.name} ({guild.id})")

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        log.error(f"Command error in {ctx.command}: {error}", exc_info=True)


async def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set in environment variables.")
    bot = IrohaBot()
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
