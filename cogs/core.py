"""Core commands - ping, test-detect, and config management."""

from __future__ import annotations

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands
from bot import config as bot_config

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

        embed = discord.Embed(
            title="Pong!",
            colour=discord.Colour.green(),
        )
        embed.add_field(name="API latency", value=f"**{api_ms}** ms")
        embed.add_field(name="Response time", value=f"**{response_ms}** ms")

        await interaction.edit_original_response(content=None, embed=embed)

    @app_commands.command(
        name="test-detect",
        description="Analyse a message against scam patterns",
    )
    @app_commands.describe(
        message_id="ID of the message to analyse",
        channel="Channel where the message is (defaults to current)",
    )
    async def test_detect(
        self,
        interaction: discord.Interaction,
        message_id: str,
        channel: discord.TextChannel = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        channel = channel or interaction.channel

        try:
            msg_id = int(message_id)
            message = await channel.fetch_message(msg_id)
        except ValueError:
            await interaction.followup.send(
                "Invalid message ID.",
                ephemeral=True,
            )
            return
        except discord.NotFound:
            await interaction.followup.send(
                f"Message not found in {channel.mention}.",
                ephemeral=True,
            )
            return
        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have access to that channel.",
                ephemeral=True,
            )
            return

        monitor = self.bot.get_cog("Monitor")
        if not monitor:
            await interaction.followup.send(
                "Monitor cog is not loaded.",
                ephemeral=True,
            )
            return

        result = await monitor.analyze_message(message)

        score = result["score"]
        is_scam = result["is_scam"]

        if is_scam:
            colour = discord.Colour.red()
            status = f"**SCAM DETECTED** (score: {score})"
        elif score >= 30:
            colour = discord.Colour.orange()
            status = f"**Suspicious** (score: {score}) - caution"
        else:
            colour = discord.Colour.green()
            status = f"**Legitimate** (score: {score})"

        embed = discord.Embed(
            title="Analysis result",
            colour=colour,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Status", value=status, inline=False)
        embed.add_field(
            name="Score",
            value=f"**{score}** / alert threshold (50)",
            inline=True,
        )

        factors = result.get("factors", [])
        if factors:
            embed.add_field(
                name="Factors",
                value="\n".join(f"- `{f}`" for f in factors),
                inline=False,
            )

        embed.add_field(
            name="Message",
            value=f"[Jump]({message.jump_url}) | Author: {message.author.mention}",
            inline=False,
        )

        if result.get("ocr_text"):
            embed.add_field(
                name="OCR text",
                value=f"```{result['ocr_text'][:500]}```",
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    config_group = app_commands.Group(
        name="config",
        description="Manage bot configuration (patterns, settings)",
    )

    @config_group.command(
        name="show",
        description="Display current configuration",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_show(self, interaction: discord.Interaction) -> None:
        """Show loaded patterns and settings."""
        await interaction.response.defer(ephemeral=True)

        patterns = bot_config.raw_patterns
        lines = []
        for p in patterns:
            enabled = p.get("enabled", True)
            mark = "+" if enabled else "-"
            lines.append(
                f"{mark} `{p['name']}` weight={p['weight']}  -- {p.get('desc', '')}"
            )
        patterns_text = "\n".join(lines) if lines else "No patterns"

        alert_channel_id = bot_config.get("alert_channel_id")
        ping_role_id = bot_config.get("ping_role_id")

        settings = {
            "score_alert": bot_config.get("score_alert", 50),
            "score_warn": bot_config.get("score_warn", 30),
            "no_text_bonus": bot_config.get("no_text_bonus", 10),
            "community_confirm_count": bot_config.get("community_confirm_count", 3),
            "image_max_size": (
                f"{bot_config.get('image_max_size', 5 * 1024 * 1024) / 1024 / 1024:.0f} MB"
            ),
            "log_channel_names": ", ".join(bot_config.get("log_channel_names", [])),
            "alert_channel_id": (
                f"<#{alert_channel_id}>" if alert_channel_id else "not set"
            ),
            "ping_role_id": (f"<@&{ping_role_id}>" if ping_role_id else "not set"),
            "report_emoji": bot_config.get("report_emoji", "\U0001f46e"),
            "message_min_length": bot_config.get("message_min_length", 15),
            "language": "+".join(bot_config.get("language", ["fr", "en"])),
            "ignored_user_ids": str(bot_config.get("ignored_user_ids", [])),
            "ignored_role_ids": str(bot_config.get("ignored_role_ids", [])),
            "ignored_channel_ids": str(bot_config.get("ignored_channel_ids", [])),
            "auto_delete": bot_config.get("auto_delete", False),
            "dm_author_on_alert": bot_config.get("dm_author_on_alert", False),
            "dm_message_template": (
                bot_config.get("dm_message_template", "")[:60] + "..."
                if len(bot_config.get("dm_message_template", "")) > 60
                else bot_config.get("dm_message_template", "")
            ),
            "cooldown_seconds": bot_config.get("cooldown_seconds", 300),
            "banned_images_dir": bot_config.get("banned_images_dir", "banned_images"),
            "banned_images_threshold": bot_config.get("banned_images_threshold", 20),
            "banned_images_score": bot_config.get("banned_images_score", 50),
            "debug_mode": bot_config.get("debug_mode", False),
            "enable_report": bot_config.get("enable_report", True),
            "logging_level": bot_config.get("logging_level", "INFO"),
        }
        settings_text = "\n".join(f"- `{k}` -> {v}" for k, v in settings.items())

        embed = discord.Embed(
            title="Bot configuration",
            colour=discord.Colour.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Patterns",
            value=f"```{patterns_text[:900]}```",
            inline=False,
        )
        embed.add_field(name="Settings", value=settings_text, inline=False)
        embed.set_footer(text=f"{len(patterns)} patterns loaded")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @config_group.command(
        name="reload",
        description="Reload configuration from JSON files",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_reload(self, interaction: discord.Interaction) -> None:
        """Reload config/patterns.json and config/settings.json."""
        await interaction.response.defer(ephemeral=True)
        try:
            bot_config.reload()
            await interaction.followup.send(
                f"Configuration reloaded - {len(bot_config.raw_patterns)} patterns, "
                f"{len(bot_config.patterns)} compiled.",
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.followup.send(
                f"Reload error: {exc}",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Core(bot))
