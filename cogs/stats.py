"""Stats commands — per-guild and global detection statistics."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands
from core.stats import get_stats

log = logging.getLogger("cogs.stats")


class Stats(commands.Cog, name="Stats"):
    """Detection statistics."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="stats", description="Show detection statistics for this server")
    async def stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        sm = get_stats(interaction.guild_id)
        first = sm.get("first_seen", 0)
        embed = discord.Embed(
            title=f"📊 Detection stats — {interaction.guild.name}",
            colour=discord.Colour.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="📈 Summary", value=sm.summary(), inline=False)
        embed.add_field(name="First tracked", value=f"<t:{first}:R>" if first else "N/A", inline=True)
        embed.set_footer(text=f"ID: {interaction.guild_id}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="stats-reset", description="Reset detection statistics for this server")
    @app_commands.default_permissions(manage_guild=True)
    async def stats_reset(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        sm = get_stats(interaction.guild_id)
        sm.reset()
        await interaction.followup.send("Stats reset.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Stats(bot))
