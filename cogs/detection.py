"""Detection engine: OCR, image similarity, pattern scoring."""

from __future__ import annotations

import io
import logging
import re
from typing import Optional

import aiohttp
import discord
from core.config import GuildConfig

log = logging.getLogger("cogs.detection")


class Detector:
    """OCR extraction, banned image matching, and weighted pattern scoring."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self._ocr = None

    # ── OCR ──────────────────────────────────────────────────────────

    @property
    def ocr(self):
        if self._ocr is None:
            import easyocr
            from bot import config as global_cfg

            lang = global_cfg.get("language", ["fr", "en"])
            log.info("Initialising easyocr (CPU, %s) ...", "+".join(lang))
            self._ocr = easyocr.Reader(lang, gpu=False)
            log.info("easyocr ready")
        return self._ocr

    async def ocr_image(self, url: str, max_ocr_len: int = 2000, max_size: int = 5242880) -> Optional[str]:
        """Download image and extract text via OCR."""
        data = await self._download(url, max_size)
        if data is None:
            return None
        log.debug("Running OCR on %s (%d bytes) ...", url, len(data))
        try:
            results = await self.bot.loop.run_in_executor(None, self._run_ocr, io.BytesIO(data))
            if results:
                text = " ".join(r[1] for r in results)
                log.debug("OCR extracted %d chars from %s", len(text), url)
                return text[:max_ocr_len]
        except Exception as exc:
            log.debug("OCR failed for %s: %s", url, exc)
        return None

    def _run_ocr(self, data: io.BytesIO) -> list:
        import numpy as np
        from PIL import Image

        img = Image.open(data)
        if img.mode != "RGB":
            img = img.convert("RGB")
        return self.ocr.readtext(np.array(img))

    # ── Banned image hashes (phash) ──────────────────────────────────

    def _banned_hashes(self, gc: GuildConfig):
        attr = "_banned_hashes_cache"
        cached = getattr(self, attr, None)
        if cached is not None:
            return cached
        hashes: list = []
        banned_dir = gc.get("banned_images_dir", "banned_images")
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
                            log.debug("Skipping %s: %s", f.name, exc)
            except Exception as exc:
                log.warning("Failed to load banned images: %s", exc)
        log.debug("Loaded %d banned hashes from %s", len(hashes), banned_dir)
        setattr(self, attr, hashes)
        return hashes

    async def check_banned_image(self, image_bytes: bytes, gc: GuildConfig) -> Optional[dict]:
        """Compare image bytes against banned phashes."""
        banned = self._banned_hashes(gc)
        if not banned:
            return None
        try:
            from PIL import Image
            import imagehash

            img = Image.open(io.BytesIO(image_bytes))
            h = imagehash.phash(img)
            threshold = gc.get("banned_images_threshold", 20)
            for fname, bh in banned:
                d = h - bh
                if d <= threshold:
                    sim = max(0, 100 - (d / 64) * 100)
                    return {"matched": fname, "distance": int(d), "similarity": round(sim, 1)}
        except Exception as exc:
            log.debug("phash failed: %s", exc)
        return None

    # ── Pattern matching ─────────────────────────────────────────────

    async def analyze_message(self, message: discord.Message, gc: GuildConfig) -> dict:
        """Score message against guild patterns.

        Returns {is_scam, score, reason, details, ocr_text, images, factors}.
        """
        result = {"is_scam": False, "score": 0, "reason": "", "details": "", "ocr_text": "", "images": [], "factors": []}

        all_text = (message.content.strip() + "\n") if message.content.strip() else ""
        urls = await self._get_image_urls(message, gc)
        max_size = gc.get("image_max_size", 5242880)

        for url in urls:
            text = await self.ocr_image(url, max_size=max_size)
            if text:
                result["ocr_text"] += text + "\n"
                all_text += text + "\n"

        all_text = all_text.strip()
        if not all_text:
            return result

        factors: list[tuple[str, int]] = []
        details: list[str] = []

        for name, pattern, weight, enabled in gc.get_compiled_patterns():
            if pattern.search(all_text):
                factors.append((name, weight))
                details.append(f"{name} ({weight})")
                log.debug("Pattern matched msg %d: %s (weight %d)", message.id, name, weight)

        if not message.content.strip() and result["ocr_text"] and factors:
            bonus = gc.get("no_text_bonus", 10)
            factors.append(("no_text", bonus))
            details.append(f"no_text (+{bonus})")

        total = sum(w for _, w in factors)
        result["score"] = total
        result["factors"] = [f"{n} ({p})" for n, p in factors]

        score_alert = gc.get("score_alert", 50)
        score_warn = gc.get("score_warn", 30)

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

    # ── Image helpers ────────────────────────────────────────────────

    async def _download(self, url: str, max_size: int = 5242880) -> Optional[bytes]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.read()
                    if len(data) > max_size:
                        return None
                    return data
        except Exception:
            return None

    async def _get_image_urls(self, msg: discord.Message, gc: GuildConfig) -> list[str]:
        exts = tuple(gc.get("supported_extensions", [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]))
        urls = list(
            dict.fromkeys(
                a.url for a in msg.attachments if any(a.filename.lower().endswith(e) for e in exts)
            )
        )
        for e in msg.embeds:
            if e.image and e.image.url and e.image.url not in urls:
                urls.append(e.image.url)
            if e.thumbnail and e.thumbnail.url and e.thumbnail.url not in urls:
                urls.append(e.thumbnail.url)
        if msg.content:
            img_re = gc.get("image_url_regex", r"(https?://[^\s]+\.(?:png|jpg|jpeg|gif|webp))")
            for m in re.finditer(img_re, msg.content, re.I):
                if m.group(1) not in urls:
                    urls.append(m.group(1))
        return urls
