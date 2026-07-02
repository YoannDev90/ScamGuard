"""Message surveillance — one detection, one embed, fast actions."""

from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands
from core.config import get_guild_config
from cogs._detection import Detector
from cogs._actions import execute_actions, _build_alert_embed

log = logging.getLogger("cogs.monitor")

_COOLDOWN_CLEANUP_INTERVAL = 600


class Monitor(commands.Cog, name="Monitor"):
    """Listens to messages, detects scams, executes actions, sends one alert."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.detector = Detector(bot)
        self._cooldowns: dict[int, float] = {}
        self._last_cooldown_cleanup = 0.0

    async def cog_unload(self) -> None:
        await self.detector.close()

    def _clean_cooldowns(self) -> None:
        now = time.time()
        if now - self._last_cooldown_cleanup < _COOLDOWN_CLEANUP_INTERVAL:
            return
        cutoff = now - 3600
        self._cooldowns = {k: v for k, v in self._cooldowns.items() if v >= cutoff}
        self._last_cooldown_cleanup = now

    # ── Alert embed ──────────────────────────────────────────────────

    async def _send_alert(self, message: discord.Message, result: dict, gc) -> None:
        """Send one alert embed to the configured alert channel."""
        ch_id = gc.get("alert_channel_id")
        target = self.bot.get_channel(ch_id) if ch_id else None
        if not target:
            channels = gc.get("log_channel_names", ["logs", "admin", "alerts", "anti-scam"])
            target = next((c for c in message.guild.text_channels if c.name in channels), None)
        if not target:
            return

        trigger = "banned_image" if result.get("image_flag") else "scam"
        embed = _build_alert_embed(message, result, gc, trigger=trigger)

        ping = ""
        ping_role = gc.get("ping_role_id")
        if ping_role:
            role = message.guild.get_role(ping_role)
            if role:
                ping = role.mention

        try:
            await target.send(content=ping or None, embed=embed)
        except discord.Forbidden:
            log.warning("Cannot send alert to #%s", target.name)

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

        result = await self.detector.analyze_message(message, gc)

        # Parallel banned-image check
        if urls:
            max_size = gc.get("image_max_size", 5242880)
            dl_timeout = gc.get("image_download_timeout", 30)
            download_sem = asyncio.Semaphore(10)

            async def _check(url: str):
                async with download_sem:
                    data = await self.detector._download(url, max_size, dl_timeout)
                    if data:
                        return await self.detector.check_banned_image(data, gc)
                    return None

            banned_matches = [m for m in await asyncio.gather(*[_check(u) for u in urls]) if m]
            if banned_matches:
                match = banned_matches[0]
                result["image_flag"] = {"banned": match}
                banned_score = int(gc.get("banned_images_score", 50))
                result["score"] += banned_score
                result.setdefault("factors", []).append(
                    f"banned_image ({match['matched']}, {match['similarity']}%)"
                )
                log.warning("Banned image msg %d | guild=%d | matched=%s", message.id, message.guild.id, match["matched"])

        triggered = result["is_scam"] or bool(result.get("image_flag"))

        if not triggered:
            return

        # Execute actions — one trigger, fast
        await execute_actions("scam", message, result)

        # Reactions
        reactions_cfg = gc.get("reactions", {})
        try:
            if result.get("image_flag"):
                await message.add_reaction(reactions_cfg.get("banned_image", "\U0001f51e"))
            else:
                await message.add_reaction(reactions_cfg.get("scam", "\U0001f6a8"))
        except discord.HTTPException:
            pass

        # Cooldown
        cd = gc.get("cooldown_seconds", 300)
        now = message.created_at.timestamp()
        if now - self._cooldowns.get(message.author.id, 0) < cd:
            return
        self._cooldowns[message.author.id] = now
        self._clean_cooldowns()

        log.warning("Scam msg %d | guild=%d | score=%d", message.id, message.guild.id, result["score"])

        # One alert embed
        await self._send_alert(message, result, gc)

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

        reactions_cfg = gc.get("reactions", {})
        clear_emoji = reactions_cfg.get("clear", "\u2705")

        if emoji == clear_emoji:
            for r in msg.reactions:
                if r.me:
                    async for u in r.users():
                        if u == self.bot.user:
                            await r.remove(u)
                            break

        alert_emoji = reactions_cfg.get("community_alert", "\U0001f6a8")
        if emoji == alert_emoji:
            count = sum(1 for r in msg.reactions if str(r.emoji) == alert_emoji and r.count > 1)
            if count >= gc.get("community_confirm_count", 3):
                result = {"score": 99, "is_scam": True, "factors": ["Community confirmed"]}
                await execute_actions("scam", msg, result)
                await self._send_alert(msg, result, gc)

        report_emoji = gc.get("report_emoji", "\U0001f46e")
        if gc.get("enable_report", True) and emoji == report_emoji and not any(r.me for r in msg.reactions if str(r.emoji) == report_emoji):
            result = {"score": 50, "is_scam": True, "factors": [f"Reported by <@{payload.user_id}>"]}
            await execute_actions("scam", msg, result)
            await self._send_alert(msg, result, gc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Monitor(bot))
