"""Core commands — ping and test-detect."""

from __future__ import annotations

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands
from core.config import get_guild_config

log = logging.getLogger("bot.core")


class Core(commands.Cog, name="Core"):
    """Essential bot commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Show bot latency")
    async def ping(self, interaction: discord.Interaction) -> None:
        start = time.perf_counter()
        await interaction.response.send_message("Ping …", ephemeral=True)
        end = time.perf_counter()
        api_ms = round(self.bot.latency * 1000)
        response_ms = round((end - start) * 1000)
        embed = discord.Embed(title="Pong!", colour=discord.Colour.green())
        embed.add_field(name="API latency", value=f"**{api_ms}** ms")
        embed.add_field(name="Response time", value=f"**{response_ms}** ms")
        await interaction.edit_original_response(content=None, embed=embed)

    @app_commands.command(name="test-detect", description="Analyze a message against keywords")
    @app_commands.describe(message_id="Message ID", channel="Channel (default: current)")
    async def test_detect(
        self,
        interaction: discord.Interaction,
        message_id: str,
        channel: discord.TextChannel = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        channel = channel or interaction.channel
        try:
            msg = await channel.fetch_message(int(message_id))
        except ValueError:
            await interaction.followup.send("Invalid ID.", ephemeral=True)
            return
        except discord.NotFound:
            await interaction.followup.send(f"Message not found in {channel.mention}.", ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send("Access denied.", ephemeral=True)
            return

        monitor = self.bot.get_cog("Monitor")
        if not monitor:
            await interaction.followup.send("Monitor not loaded.", ephemeral=True)
            return

        gc = get_guild_config(interaction.guild_id)
        result = await monitor.detector.analyze_message(msg, gc)
        score = result["score"]
        is_scam = result["is_scam"]

        ec = gc.get("embed_colors", {})
        if is_scam:
            colour = discord.Colour(ec.get("scam", 0xE74C3C))
            status = f"**SCAM** (score: {score})"
        elif score >= gc.get("score_warn", 30):
            colour = discord.Colour(ec.get("suspicious", 0xE67E22))
            status = f"**Suspicious** (score: {score})"
        else:
            colour = discord.Colour(ec.get("ok", 0x2ECC71))
            status = f"**OK** (score: {score})"

        embed = discord.Embed(title="Analysis result", colour=colour, timestamp=discord.utils.utcnow())
        embed.add_field(name="Status", value=status, inline=False)
        embed.add_field(name="Score", value=f"**{score}** / threshold {gc.get('score_alert', 50)}", inline=True)
        factors = result.get("factors", [])
        if factors:
            embed.add_field(name="Factors", value="\n".join(f"- `{f}`" for f in factors), inline=False)
        embed.add_field(name="Message", value=f"[Jump]({msg.jump_url}) | Author: {msg.author.mention}", inline=False)
        if result.get("ocr_text"):
            embed.add_field(name="OCR", value=f"```{result['ocr_text'][:500]}```", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Core(bot))
