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
    @app_commands.default_permissions(manage_guild=True)
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
        embed.add_field(name="Keywords", value=f"**{gc.get('score_warn', 30)}** warn / **{gc.get('score_alert', 50)}** alert", inline=True)
        factors = result.get("factors", [])
        if factors:
            embed.add_field(name="Factors", value="```\n" + "\n".join(factors[:15]) + "\n```", inline=False)
        embed.add_field(name="Message", value=f"[Jump]({msg.jump_url}) | {msg.author.mention}", inline=False)
        if result.get("ocr_text"):
            embed.add_field(name="OCR", value=f"```{result['ocr_text'][:500]}```", inline=False)
        details = result.get("details", "")
        if details:
            embed.add_field(name="Details", value=f"```{details[:500]}```", inline=False)
        embed.set_footer(text=f"ID: {msg.id}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Scan ─────────────────────────────────────────────────────────

    @app_commands.command(name="scan", description="Scan recent messages in a channel")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        channel="Channel to scan (default: current)",
        limit="Number of messages to scan (max 200, default 50)",
    )
    async def scan(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
        limit: int = 50,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        channel = channel or interaction.channel

        monitor = self.bot.get_cog("Monitor")
        if not monitor:
            await interaction.followup.send("Monitor not loaded.", ephemeral=True)
            return

        from core.config import get_guild_config
        gc = get_guild_config(interaction.guild_id)
        limit = min(limit, 200)

        status = await interaction.followup.send(f"Scanning {limit} messages in {channel.mention} …", ephemeral=True)

        total = 0
        scanned = 0
        scam_count = 0
        suspicious_count = 0
        banned_count = 0
        errors = 0

        async for msg in channel.history(limit=limit):
            total += 1
            if msg.author.bot:
                continue
            ignored_roles = gc.get_ignored("role_ids")
            if msg.author.id in gc.get_ignored("user_ids") or msg.channel.id in gc.get_ignored("channel_ids"):
                continue
            if any(r.id in ignored_roles for r in msg.author.roles):
                continue

            try:
                result = await monitor.detector.analyze_message(msg, gc)
                scanned += 1
                if result.get("image_flag"):
                    banned_count += 1
                elif result["is_scam"]:
                    scam_count += 1
                elif result["score"] >= gc.get("score_warn", 30):
                    suspicious_count += 1
            except Exception:
                errors += 1

            if total % 25 == 0:
                await status.edit(content=f"Scanning… {total}/{limit} ({scanned} analyzed)")

        embed = discord.Embed(
            title=f"✅ Scan complete — {channel.name}",
            colour=discord.Colour.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Messages checked", value=str(total), inline=True)
        if scanned != total:
            embed.add_field(name="Skipped (bots/ignored)", value=str(total - scanned), inline=True)
        embed.add_field(name="Scams detected", value=str(scam_count), inline=True)
        embed.add_field(name="Suspicious", value=str(suspicious_count), inline=True)
        embed.add_field(name="Banned images", value=str(banned_count), inline=True)
        if errors:
            embed.add_field(name="Errors", value=str(errors), inline=True)
        embed.set_footer(text=f"Limit: {limit}")
        await status.edit(content=None, embed=embed)


    # ── Welcome ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        from core.config import config
        desc = config.get("welcome_message", f"Merci d'avoir ajouté {self.bot.user.name} ! Utilisez `/setup` pour la configuration rapide ou `/guide` pour l'aide.")
        embed = discord.Embed(
            title=f"👋 Merci d'ajouter {self.bot.user.name} !",
            description=desc,
            colour=discord.Colour.blue(),
        )
        embed.add_field(name="🚀 Quick start", value="`/setup` — Configuration interactive (4 étapes)", inline=False)
        embed.add_field(name="📖 Guide", value="`/guide` — Vue d'ensemble du bot", inline=True)
        embed.add_field(name="⚙️ Config", value="`/config show` — Voir la configuration actuelle", inline=True)
        embed.add_field(name="🛡️ Protection active", value="Le bot analyse automatiquement les messages. Aucune action manuelle requise.", inline=False)
        embed.set_footer(text="ScamGuard • Questions ? /guide")
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    pass
                break


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Core(bot))
