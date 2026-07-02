"""Message surveillance — delegates to detector + action engine."""

from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands
from bot import config as global_cfg
from core.config import get_guild_config
from cogs._detection import Detector
from cogs._actions import execute_actions

log = logging.getLogger("cogs.monitor")

_COOLDOWN_CLEANUP_INTERVAL = 600  # purge stale entries every 10 min


class Monitor(commands.Cog, name="Monitor"):
    """Listens to all messages, delegates to Detector and action executors."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.detector = Detector(bot)
        self._cooldowns: dict[int, float] = {}
        self._last_cooldown_cleanup = 0.0

    async def cog_unload(self) -> None:
        await self.detector.close()

    # ── Helpers ──────────────────────────────────────────────────────

    def _clean_cooldowns(self) -> None:
        now = time.time()
        if now - self._last_cooldown_cleanup < _COOLDOWN_CLEANUP_INTERVAL:
            return
        cutoff = now - 3600  # prune > 1h old
        self._cooldowns = {k: v for k, v in self._cooldowns.items() if v >= cutoff}
        self._last_cooldown_cleanup = now

    def _legacy_embed_colour(self, score: int, gc) -> int:
        ec = gc.get("embed_colors", {})
        threshold = gc.get("embed_dark_red_threshold", 70)
        if score >= threshold:
            return discord.Colour.dark_red().value
        return ec.get("scam", 0xE74C3C)

    # ── Message handler ──────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        try:
            await self._on_message_inner(message)
        except Exception:
            log.exception("Unhandled error in on_message msg %d", message.id)

    async def _on_message_inner(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        gc = get_guild_config(message.guild.id)

        if message.author.id in gc.get_ignored("user_ids"):
            return
        if message.channel.id in gc.get_ignored("channel_ids"):
            return
        if any(role.id in gc.get_ignored("role_ids") for role in message.author.roles):
            return

        min_len = gc.get("message_min_length", 15)
        urls = await self.detector._get_image_urls(message, gc)
        if not urls and len(message.content.strip()) < min_len:
            return

        if gc.get("debug_mode", False):
            log.debug("Analyzing msg %d | guild=%d | author=%s | has_image=%s",
                       message.id, message.guild.id, message.author, bool(urls))

        result = await self.detector.analyze_message(message, gc)

        # Banned image check
        banned_match = None
        if urls:
            max_size = gc.get("image_max_size", 5242880)
            dl_timeout = gc.get("image_download_timeout", 30)
            for url in urls:
                data = await self.detector._download(url, max_size, dl_timeout)
                if data is None:
                    continue
                banned_match = await self.detector.check_banned_image(data, gc)
                if banned_match:
                    break

        if banned_match:
            result["image_flag"] = {"banned": banned_match}
            banned_score = int(gc.get("banned_images_score", 50))
            result["score"] += banned_score
            result.setdefault("factors", []).append(
                f"banned_image ({banned_match['matched']}, {banned_match['similarity']}%)"
            )
            log.warning("Banned image msg %d | guild=%d | matched=%s", message.id, message.guild.id, banned_match["matched"])

        # Execute actions
        if result["is_scam"]:
            await execute_actions("scam", message, result)
        elif result["score"] >= gc.get("score_warn", 30):
            await execute_actions("suspicious", message, result)
        if banned_match:
            await execute_actions("banned_image", message, result)

        # Reactions
        has_image_flag = bool(banned_match)
        reactions_cfg = gc.get("reactions", {})
        try:
            if has_image_flag:
                await message.add_reaction(reactions_cfg.get("banned_image", "\U0001f51e"))
            if result["is_scam"]:
                await message.add_reaction(reactions_cfg.get("scam", "\U0001f6a8"))
            elif result["score"] >= gc.get("score_warn", 30):
                await message.add_reaction(reactions_cfg.get("suspicious", "\u26a0\ufe0f"))
        except discord.HTTPException:
            pass

        # Legacy alerts
        if has_image_flag:
            await self._legacy_report_banned(message, result, gc)

        if result["is_scam"]:
            cd = gc.get("cooldown_seconds", 300)
            now = message.created_at.timestamp()
            if now - self._cooldowns.get(message.author.id, 0) < cd:
                return
            self._cooldowns[message.author.id] = now
            self._clean_cooldowns()
            log.warning("Scam msg %d | guild=%d | score=%d", message.id, message.guild.id, result["score"])
            await self._legacy_notify(message, result, gc)

    # ── Legacy helpers ───────────────────────────────────────────────

    async def _legacy_notify(self, message: discord.Message, result: dict, gc) -> None:
        if gc.get_actions("scam") and any(a["type"] in ("notify_channel", "notify_role", "notify_user") for a in gc.get_actions("scam")):
            return
        ch_id = gc.get("alert_channel_id")
        target = self.bot.get_channel(ch_id) if ch_id else None
        if not target:
            channels = gc.get("log_channel_names", ["logs", "admin", "alerts"])
            target = next((c for c in message.guild.text_channels if c.name in channels), message.channel)
        ping = ""
        ping_role = gc.get("ping_role_id")
        if ping_role:
            role = message.guild.get_role(ping_role)
            if role:
                ping = role.mention
        score = result.get("score", 0)
        embed = discord.Embed(
            title="🚨 Scam detected",
            colour=self._legacy_embed_colour(score, gc),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Author", value=message.author.mention, inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        content = message.content
        if content:
            embed.add_field(name="Message", value=f"```{content[:1000]}```", inline=False)
        factors = result.get("factors", [])
        if factors:
            embed.add_field(name="Reports", value="\n".join(f"- {f}" for f in factors), inline=False)
        embed.set_footer(text=f"ID: {message.id}")
        try:
            await target.send(content=ping or None, embed=embed)
        except discord.Forbidden:
            log.warning("Cannot send legacy alert to #%s", target.name)
        if gc.get("auto_delete", False):
            try:
                await message.delete()
            except discord.Forbidden:
                pass
        if gc.get("dm_author_on_alert", False):
            warn_msg = gc.get("warn_message_default", "Your message has been flagged.")
            try:
                await message.author.send(
                    f"{warn_msg}\nServer: {message.guild.name}\nChannel: {message.channel.mention}"
                )
            except discord.Forbidden:
                pass

    async def _legacy_report_banned(self, message: discord.Message, result: dict, gc) -> None:
        if gc.get_actions("banned_image") and any(a["type"] in ("notify_channel", "log") for a in gc.get_actions("banned_image")):
            return
        ch_id = gc.get("alert_channel_id")
        target = self.bot.get_channel(ch_id) if ch_id else None
        if not target:
            channels = gc.get("log_channel_names", ["logs", "admin", "alerts"])
            target = next((c for c in message.guild.text_channels if c.name in channels), message.channel)
        banned = result.get("image_flag", {}).get("banned")
        ec = gc.get("embed_colors", {})
        embed = discord.Embed(
            title="🔞 Banned image detected",
            colour=discord.Colour(ec.get("banned_image", 0x9B59B6)),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Author", value=message.author.mention, inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        content = message.content
        if content:
            embed.add_field(name="Message", value=f"```{content[:1000]}```", inline=False)
        if banned:
            embed.add_field(name="Matched", value=f"`{banned['matched']}` ({banned['similarity']}%)", inline=False)
        embed.set_footer(text=f"ID: {message.id}")
        try:
            await target.send(embed=embed)
        except discord.Forbidden:
            pass
        if gc.get("auto_delete", False):
            try:
                await message.delete()
            except discord.Forbidden:
                pass

    # ── Community reaction system ────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == self.bot.user.id or not payload.guild_id:
            return
        gc = get_guild_config(payload.guild_id)
        emoji = str(payload.emoji)
        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return
        try:
            msg = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        report_emoji = gc.get("report_emoji", "\U0001f46e")
        if gc.get("enable_report", True) and emoji == report_emoji and not any(r.me for r in msg.reactions if str(r.emoji) == report_emoji):
            await self._legacy_notify(msg, {"score": 0, "is_scam": False, "factors": [f"Reported by <@{payload.user_id}>"]}, gc)

        reactions_cfg = gc.get("reactions", {})
        clear_emoji = reactions_cfg.get("clear", "\u2705")
        alert_emoji = reactions_cfg.get("community_alert", "\U0001f6a8")

        if emoji == clear_emoji:
            for r in msg.reactions:
                if r.me:
                    async for u in r.users():
                        if u == self.bot.user:
                            await r.remove(u)
                            break

        if emoji == alert_emoji:
            count = sum(1 for r in msg.reactions if str(r.emoji) == alert_emoji and r.count > 1)
            if count >= gc.get("community_confirm_count", 3):
                await self._legacy_notify(msg, {"score": 99, "is_scam": True, "factors": ["Community confirmed"]}, gc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Monitor(bot))
