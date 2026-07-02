"""Message surveillance — one detection, one embed, fast actions."""

from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands
from core.config import get_guild_config
from core.stats import get_stats
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

    async def _batch_cleanup(self, message: discord.Message) -> None:
        """Delete recent messages from the same author in the same channel."""
        try:
            to_delete = []
            async for msg in message.channel.history(limit=50, before=message):
                if msg.author.id == message.author.id:
                    to_delete.append(msg)
            while to_delete:
                batch = to_delete[:100]
                to_delete = to_delete[100:]
                if len(batch) == 1:
                    await batch[0].delete()
                else:
                    await message.channel.delete_messages(batch)
            log.info("Batch cleanup: deleted messages from user %d in #%s",
                     message.author.id, message.channel.name)
        except discord.Forbidden:
            log.debug("Batch cleanup: missing manage_messages in #%s", message.channel.name)
        except discord.HTTPException as e:
            log.debug("Batch cleanup: HTTP error %s", e)

    # ── Alert embed ──────────────────────────────────────────────────

    async def _send_alert(self, message: discord.Message, result: dict, gc) -> None:
        ch_id = gc.get("alert_channel_id")
        target = self.bot.get_channel(ch_id) if ch_id else None
        if not target:
            channels = gc.get("log_channel_names", ["logs", "admin", "alerts", "anti-scam"])
            target = next((c for c in message.guild.text_channels if c.name in channels), None)
        if not target:
            return

        trigger = "banned_image" if result.get("image_flag") else ("scam" if result.get("is_scam") else "suspicious")
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

    # ── Main message handler ─────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        try:
            await self._on_message_inner(message)
        except Exception:
            log.exception("Unhandled error in on_message msg %d", message.id)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if after.author.bot or not after.guild:
            return
        if before.content == after.content and [a.url for a in before.attachments] == [a.url for a in after.attachments]:
            return
        try:
            await self._on_message_inner(after)
        except Exception:
            log.exception("Unhandled error in on_message_edit msg %d", after.id)

    async def _on_message_inner(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        gc = get_guild_config(message.guild.id)
        uid, cid, gid = message.author.id, message.channel.id, message.guild.id

        if uid in gc.get_ignored("user_ids"):
            return
        if cid in gc.get_ignored("channel_ids"):
            return
        ignored_roles = [r.id for r in message.author.roles if r.id in gc.get_ignored("role_ids")]
        if ignored_roles:
            return

        min_len = gc.get("message_min_length", 15)
        urls = await self.detector._get_image_urls(message, gc)
        if not urls and len(message.content.strip()) < min_len:
            return

        result = await self.detector.analyze_message(message, gc)
        is_scam = result["is_scam"] or bool(result.get("image_flag"))
        is_sus = not is_scam and result["score"] >= gc.get("score_warn", 30)

        # Record stats
        sm = get_stats(gid)
        sm.increment_scanned()
        if is_scam:
            if result.get("image_flag"):
                sm.increment_banned_image()
            else:
                sm.increment_scam()
        elif is_sus:
            sm.increment_suspicious()

        if not is_scam and not is_sus:
            sm.flush()
            return

        # Reaction (visual feedback)
        reactions_cfg = gc.get("reactions", {})
        try:
            e_key = "banned_image" if result.get("image_flag") else ("scam" if is_scam else "suspicious")
            emoji = reactions_cfg.get(e_key, "\U0001f6a8")
            await message.add_reaction(emoji)
        except discord.HTTPException:
            pass

        # Cooldown: only skips alert spam, NOT actions
        cd = gc.get("cooldown_seconds", 300)
        now = message.created_at.timestamp()
        last = self._cooldowns.get(uid, 0)
        on_cooldown = (now - last) < cd

        trigger = "scam" if is_scam else "suspicious"
        actions = gc.get_actions(trigger)
        action_types = [a.get("type", "") for a in actions]

        # Execute actions (always, cooldown or not)
        if actions:
            await execute_actions(trigger, message, result)
            sm.increment_actions()
            # Batch cleanup: if actions include delete, purge recent messages from same user
            if "delete" in action_types and message.channel.permissions_for(message.guild.me).manage_messages:
                await self._batch_cleanup(message)

        sm.flush()
        self._cooldowns[uid] = now
        self._clean_cooldowns()
        log.warning("DETECTED guild=%d msg=%d author=%d score=%d trigger=%s", gid, message.id, uid, result["score"], trigger)

        # Alert skipped if on cooldown (avoid spam in alert channel)
        if not on_cooldown:
            await self._send_alert(message, result, gc)
        else:
            log.debug("Alert skip (cooldown) user=%d msg=%d", uid, message.id)

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
