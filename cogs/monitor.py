"""Scam surveillance - OCR text extraction + weighted pattern scoring + image hash matching."""

from __future__ import annotations

import asyncio
import io
import logging
import re
from typing import Optional

import aiohttp
import discord
from discord.ext import commands
from bot import config as bot_config

log = logging.getLogger("bot.monitor")


class Monitor(commands.Cog, name="Monitor"):
    """Listens to all messages, runs OCR on images, and scores against scam patterns."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._ocr = None
        self._cooldowns: dict[int, float] = {}

    @property
    def ocr(self):
        if self._ocr is None:
            import easyocr

            lang = bot_config.get("language", ["fr", "en"])
            log.info("Initialising easyocr (CPU, %s) ...", "+".join(lang))
            self._ocr = easyocr.Reader(lang, gpu=False)
            log.info("easyocr ready")
        return self._ocr

    async def analyze_message(self, message: discord.Message) -> dict:
        """Score a message against scam patterns.

        Returns a dict with keys: is_scam, score, reason, details, ocr_text, images, factors.
        """
        result: dict = {
            "is_scam": False,
            "score": 0,
            "reason": "",
            "details": "",
            "ocr_text": "",
            "images": [],
            "factors": [],
        }

        all_text = message.content.strip() + "\n" if message.content.strip() else ""

        for url in await self._get_image_urls(message):
            text = await self._ocr_image(url)
            if text:
                result["ocr_text"] += text + "\n"
                all_text += text + "\n"

        all_text = all_text.strip()
        if not all_text:
            log.debug("Message %d has no text content, skipping", message.id)
            return result

        factors: list[tuple[str, int]] = []
        details: list[str] = []

        for name, pattern, weight, enabled in bot_config.patterns:
            if not enabled:
                continue
            if pattern.search(all_text):
                factors.append((name, weight))
                details.append(f"{name} ({weight})")
                log.debug(
                    "Pattern matched on msg %d: %s (weight %d)",
                    message.id,
                    name,
                    weight,
                )

        if not message.content.strip() and result["ocr_text"] and factors:
            bonus = bot_config.get("no_text_bonus", 10)
            factors.append(("no_text", bonus))
            details.append(f"no_text (+{bonus})")

        total = sum(w for _, w in factors)
        result["score"] = total
        result["factors"] = [f"{n} ({p})" for n, p in factors]

        score_alert = bot_config.get("score_alert", 50)
        score_warn = bot_config.get("score_warn", 30)

        if total >= score_alert:
            result["is_scam"] = True
            result["reason"] = f"Score {total}\n" + "\n".join(details)
            result["details"] = "\n".join(details)
        elif total >= score_warn:
            result["reason"] = f"Score {total} (warning)"
            result["details"] = "\n".join(details)
        else:
            result["reason"] = f"Score {total}"

        return result

    # ── Banned image hashes (phash) ──────────────────────────────────

    @property
    def _banned_hashes(self):
        """Lazy-load and cache phashes from the banned_images directory."""
        attr = "_banned_hashes_cache"
        cached = getattr(self, attr, None)
        if cached is not None:
            return cached
        hashes: list = []
        banned_dir = bot_config.get("banned_images_dir", "banned_images")
        import pathlib
        p = pathlib.Path(banned_dir)
        if p.is_dir():
            try:
                from PIL import Image
                import imagehash
                for f in sorted(p.iterdir()):
                    if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
                        try:
                            img = Image.open(f)
                            h = imagehash.phash(img)
                            hashes.append((f.name, h))
                        except Exception as exc:
                            log.debug("Skipping banned image %s: %s", f.name, exc)
            except Exception as exc:
                log.warning("Failed to load banned images: %s", exc)
        log.info("Loaded %d banned image hash(es) from %s", len(hashes), banned_dir)
        setattr(self, attr, hashes)
        return hashes

    async def _check_banned_image(self, image_bytes: bytes) -> Optional[dict]:
        """Check image bytes against banned phashes.

        Returns {matched, distance, filename} if a match is found, else None.
        """
        banned = self._banned_hashes
        if not banned:
            return None
        try:
            from PIL import Image
            import imagehash
            import io as _io
            img = Image.open(_io.BytesIO(image_bytes))
            h = imagehash.phash(img)
            threshold = bot_config.get("banned_images_threshold", 20)
            for fname, bh in banned:
                d = h - bh
                if d <= threshold:
                    similarity = max(0, 100 - (d / 64) * 100)
                    return {
                        "matched": fname,
                        "distance": int(d),
                        "similarity": round(similarity, 1),
                    }
        except Exception as exc:
            log.debug("phash comparison failed: %s", exc)
        return None

    @staticmethod
    async def _get_image_urls(msg: discord.Message) -> list[str]:
        """Collect image URLs from attachments, embeds, and inline links."""
        exts = tuple(
            bot_config.get(
                "supported_extensions",
                [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"],
            )
        )
        urls = list(
            dict.fromkeys(
                a.url
                for a in msg.attachments
                if any(a.filename.lower().endswith(e) for e in exts)
            )
        )
        for e in msg.embeds:
            if e.image and e.image.url and e.image.url not in urls:
                urls.append(e.image.url)
            if e.thumbnail and e.thumbnail.url and e.thumbnail.url not in urls:
                urls.append(e.thumbnail.url)
        if msg.content:
            img_re = bot_config.get(
                "image_url_regex",
                r"(https?://[^\s]+\.(?:png|jpg|jpeg|gif|webp))",
            )
            for m in re.finditer(img_re, msg.content, re.I):
                if m.group(1) not in urls:
                    urls.append(m.group(1))
        log.debug("Found %d image URL(s) in msg %d", len(urls), msg.id)
        return urls

    async def _download_image(self, url: str) -> Optional[bytes]:
        """Download an image and return raw bytes.  Respects max_size."""
        max_size = bot_config.get("image_max_size", 5 * 1024 * 1024)
        timeout = bot_config.get("image_download_timeout", 30)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=timeout)
                ) as resp:
                    if resp.status != 200:
                        log.debug("Image fetch returned %d for %s", resp.status, url)
                        return None
                    data = await resp.read()
                    if len(data) > max_size:
                        log.debug("Image too large (%d bytes): %s", len(data), url)
                        return None
                    return data
        except Exception as exc:
            log.debug("Image download failed for %s: %s", url, exc)
        return None

    async def _ocr_image(self, url: str) -> Optional[str]:
        """Download and run OCR on a single image URL.  Returns extracted text or None."""
        max_ocr_len = bot_config.get("max_ocr_length", 2000)
        data = await self._download_image(url)
        if data is None:
            return None
        log.debug("Running OCR on %s (%d bytes) ...", url, len(data))
        try:
            results = await self.bot.loop.run_in_executor(
                None,
                self._run_ocr,
                io.BytesIO(data),
            )
            if results:
                text = " ".join(r[1] for r in results)
                log.debug("OCR extracted %d chars from %s", len(text), url)
                return text[:max_ocr_len]
        except Exception as exc:
            log.debug("OCR failed for %s: %s", url, exc)
        return None

    def _run_ocr(self, data: io.BytesIO) -> list:
        """Blocking OCR call - runs in executor thread."""
        import numpy as np
        from PIL import Image

        img = Image.open(data)
        if img.mode != "RGB":
            img = img.convert("RGB")
        return self.ocr.readtext(np.array(img))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        if message.author.id in bot_config.get("ignored_user_ids", []):
            return
        if message.channel.id in bot_config.get("ignored_channel_ids", []):
            return
        if any(
            role.id in bot_config.get("ignored_role_ids", [])
            for role in message.author.roles
        ):
            return

        min_len = bot_config.get("message_min_length", 15)
        urls = await self._get_image_urls(message)
        if not urls and len(message.content.strip()) < min_len:
            return

        if bot_config.get("debug_mode", False):
            log.debug(
                "Analyzing msg %d | author=%s | channel=%s | has_image=%s",
                message.id,
                message.author,
                message.channel.name,
                bool(urls),
            )

        result = await self.analyze_message(message)

        # ── Image analysis: banned image hash matching ────────────────
        banned_match = None
        if urls:
            for url in urls:
                data = await self._download_image(url)
                if data is None:
                    continue
                if not banned_match:
                    banned_match = await self._check_banned_image(data)
                if banned_match:
                    break

        if banned_match:
            result["image_flag"] = {"banned": banned_match}
            banned_score = int(bot_config.get("banned_images_score", 50))
            result["score"] += banned_score
            result.setdefault("factors", []).append(
                f"banned_image ({banned_match['matched']}, {banned_match['similarity']}%)"
            )
            log.warning(
                "Image flag msg %d | banned=%s | author=%s",
                message.id,
                banned_match["matched"],
                message.author,
            )

        # ── Reactions ─────────────────────────────────────────────────
        has_image_flag = bool(banned_match)
        try:
            if has_image_flag:
                await message.add_reaction("\U0001f51e")  # 🔞
            if result["is_scam"]:
                await message.add_reaction("\U0001f6a8")  # 🚨
            elif result["score"] >= bot_config.get("score_warn", 30):
                await message.add_reaction("\u26a0\ufe0f")  # ⚠️
        except discord.HTTPException:
            pass

        # ── Alerts ────────────────────────────────────────────────────
        if has_image_flag:
            await self._report_image_flag(message, result)
        if result["is_scam"]:
            cooldown = bot_config.get("cooldown_seconds", 300)
            now = message.created_at.timestamp()
            last = self._cooldowns.get(message.author.id, 0)
            if now - last < cooldown:
                log.debug(
                    "Skipping alert for user %d (cooldown %ds)",
                    message.author.id,
                    cooldown,
                )
                return
            self._cooldowns[message.author.id] = now
            log.warning(
                "Scam msg %d | score=%d | author=%s",
                message.id,
                result["score"],
                message.author,
            )
            await self._notify(message, result)
        elif result["score"] >= bot_config.get("score_warn", 30):
            log.info(
                "Suspicious msg %d | score=%d | %s",
                message.id,
                result["score"],
                message.author,
            )

    async def _notify(self, message: discord.Message, result: dict) -> None:
        """Send an alert embed to the configured notification channel."""
        channel_id = bot_config.get("alert_channel_id")
        target: Optional[discord.TextChannel] = None
        if channel_id:
            target = self.bot.get_channel(channel_id)
        if not target:
            channels = bot_config.get(
                "log_channel_names",
                ["logs", "admin", "alerts", "moderation", "anti-scam"],
            )
            target = next(
                (c for c in message.guild.text_channels if c.name in channels),
                message.channel,
            )

        ping = ""
        ping_role_id = bot_config.get("ping_role_id")
        if ping_role_id:
            role = message.guild.get_role(ping_role_id)
            if role:
                ping = role.mention

        embed = discord.Embed(
            title=f"Scam alert (score: {result['score']})",
            colour=discord.Colour.dark_red()
            if result["score"] >= 70
            else discord.Colour.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Author", value=message.author.mention, inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        factors = result.get("factors", [])
        if factors:
            embed.add_field(
                name="Factors",
                value="\n".join(f"- {f}" for f in factors),
                inline=False,
            )
        embed.add_field(
            name="Message", value=f"[Jump]({message.jump_url})", inline=False
        )
        if result.get("ocr_text"):
            text = result["ocr_text"]
            max_len = 1000
            if len(text) > max_len:
                text = text[: max_len - 3] + "..."
            embed.add_field(
                name="OCR text",
                value=f"```{text}```",
                inline=False,
            )
        embed.set_footer(text=f"ID: {message.id}")

        try:
            await target.send(content=ping or None, embed=embed)
        except discord.Forbidden:
            log.warning("Cannot send alert to %s (no permission)", target.name)

        if bot_config.get("auto_delete", False) and result.get("is_scam"):
            try:
                await message.delete()
                log.info("Auto-deleted scam msg %d", message.id)
            except discord.Forbidden:
                log.warning("Cannot delete msg %d (no permission)", message.id)

        if bot_config.get("dm_author_on_alert", False):
            try:
                dm_tpl = bot_config.get(
                    "dm_message_template",
                    "Your message in {channel} was flagged as potential scam (score: {score}). "
                    "If you believe this is an error, please contact a moderator.",
                )
                dm_msg = (
                    dm_tpl.replace("{channel}", message.channel.mention)
                    .replace("{score}", str(result["score"]))
                )
                await message.author.send(dm_msg)
            except discord.Forbidden:
                log.debug("Cannot DM user %d (DMs closed)", message.author.id)

    async def _report_image_flag(self, message: discord.Message, result: dict) -> None:
        """Send a banned-image alert to the notification channel."""
        channel_id = bot_config.get("alert_channel_id")
        target: Optional[discord.TextChannel] = None
        if channel_id:
            target = self.bot.get_channel(channel_id)
        if not target:
            channels = bot_config.get(
                "log_channel_names",
                ["logs", "admin", "alerts", "moderation", "anti-scam"],
            )
            target = next(
                (c for c in message.guild.text_channels if c.name in channels),
                message.channel,
            )

        img_flag = result.get("image_flag", {})
        banned = img_flag.get("banned")

        reasons: list[str] = []
        if banned:
            reasons.append(f"Banned image match: {banned['matched']} ({banned['similarity']}% similar)")

        embed = discord.Embed(
            title="\U0001f51e Banned image detected",
            colour=discord.Colour.purple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Author", value=message.author.mention, inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        if reasons:
            embed.add_field(
                name="Reason",
                value="\n".join(f"- {r}" for r in reasons),
                inline=False,
            )
        embed.add_field(
            name="Message", value=f"[Jump]({message.jump_url})", inline=False
        )
        embed.set_footer(text=f"ID: {message.id}")

        try:
            await target.send(embed=embed)
        except discord.Forbidden:
            log.warning(
                "Cannot send image flag alert to %s (no permission)", target.name
            )

        if bot_config.get("auto_delete", False):
            try:
                await message.delete()
                log.info("Auto-deleted flagged msg %d", message.id)
            except discord.Forbidden:
                log.warning("Cannot delete msg %d (no permission)", message.id)

        if bot_config.get("dm_author_on_alert", False):
            try:
                await message.author.send(
                    f"Your message in {message.channel.mention} was automatically flagged "
                    f"for containing a banned image. Please review the server rules."
                )
            except discord.Forbidden:
                log.debug("Cannot DM user %d (DMs closed)", message.id)

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        if payload.user_id == self.bot.user.id or not payload.guild_id:
            return

        emoji = str(payload.emoji)
        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return
        try:
            msg = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        report_emoji = bot_config.get("report_emoji", "\U0001f46e")  # 👮

        if (
            bot_config.get("enable_report", True)
            and emoji == report_emoji
            and not any(r.me for r in msg.reactions if str(r.emoji) == report_emoji)
        ):
            log.info(
                "Message %d reported by user %d",
                msg.id,
                payload.user_id,
            )
            await self._notify(
                msg,
                {
                    "score": 0,
                    "is_scam": False,
                    "factors": [f"Reported by <@{payload.user_id}>"],
                    "ocr_text": "",
                },
            )

        if emoji == "\u2705":  # ✅
            for r in msg.reactions:
                if r.me:
                    async for u in r.users():
                        if u == self.bot.user:
                            await r.remove(u)
                            break
            log.info("False positive reported on msg %d", msg.id)

        if emoji == "\U0001f6a8":  # 🚨
            count = sum(
                1 for r in msg.reactions if str(r.emoji) == "\U0001f6a8" and r.count > 1
            )
            if count >= bot_config.get("community_confirm_count", 3):
                log.info("Community confirmed scam on msg %d", msg.id)
                await self._notify(
                    msg,
                    {
                        "score": 99,
                        "is_scam": True,
                        "factors": ["Community confirmed (3+ alerts)"],
                        "ocr_text": "",
                    },
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Monitor(bot))
