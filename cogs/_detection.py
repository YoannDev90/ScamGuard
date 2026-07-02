"""Detection engine: OCR, image similarity, pattern scoring."""

from __future__ import annotations

import asyncio
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
        self._session: aiohttp.ClientSession | None = None
        self._ocr_sem = asyncio.Semaphore(4)

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

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

    async def preload_ocr(self) -> None:
        """Force OCR model load in thread pool."""
        await self.bot.loop.run_in_executor(None, lambda: self.ocr)

    async def ocr_image(self, url: str, max_ocr_len: int = 2000, max_size: int = 5242880, timeout: int = 30) -> Optional[str]:
        """Download image and extract text via OCR."""
        data = await self._download(url, max_size, timeout)
        if data is None:
            return None
        return await self._ocr_bytes(data, max_ocr_len)

    async def _ocr_bytes(self, data: bytes, max_ocr_len: int = 2000) -> Optional[str]:
        """Run OCR on image bytes."""
        async with self._ocr_sem:
            log.debug("Running OCR on %d bytes ...", len(data))
            try:
                results = await self.bot.loop.run_in_executor(None, self._run_ocr, io.BytesIO(data))
                if results:
                    text = " ".join(r[1] for r in results)
                    log.debug("OCR extracted %d chars", len(text))
                    return text[:max_ocr_len]
            except Exception as exc:
                log.debug("OCR failed: %s", exc)
            return None

    def _run_ocr(self, data: io.BytesIO) -> list:
        import numpy as np
        from PIL import Image

        img = Image.open(data)
        if img.mode != "RGB":
            img = img.convert("RGB")
        return self.ocr.readtext(np.array(img))

    # ── Banned image hashes (phash) ──────────────────────────────────

    def invalidate_banned_cache(self) -> None:
        """Clear banned images hash cache (call after adding new images)."""
        self._banned_hashes_cache = None

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
        """Score message against guild patterns."""
        result = {"is_scam": False, "score": 0, "reason": "", "details": "", "ocr_text": "", "images": [], "factors": []}

        all_text = (message.content.strip() + "\n") if message.content.strip() else ""
        urls = await self._get_image_urls(message, gc)
        max_size = gc.get("image_max_size", 5242880)
        dl_timeout = gc.get("image_download_timeout", 30)
        ocr_max = gc.get("max_ocr_length", 10000)

        log.debug("analyze msg=%d guild=%d text_len=%d images=%d", message.id, message.guild.id if message.guild else 0, len(all_text.strip()), len(urls))

        if urls:
            download_sem = asyncio.Semaphore(10)

            async def _dl(url: str) -> tuple[str, bytes | None]:
                async with download_sem:
                    data = await self._download(url, max_size, dl_timeout)
                    if data:
                        log.debug("Downloaded %s (%d bytes)", url, len(data))
                    else:
                        log.debug("Download failed %s", url)
                    return url, data

            downloaded = await asyncio.gather(*[_dl(u) for u in urls])
            tasks = [self._ocr_bytes(d, ocr_max) for _, d in downloaded if d is not None]
            if tasks:
                log.debug("Running OCR on %d images in parallel", len(tasks))
            ocr_results = await asyncio.gather(*tasks) if tasks else []
            for text in ocr_results:
                if text:
                    result["ocr_text"] += text + "\n"
                    all_text += text + "\n"

        all_text = all_text.strip()
        if not all_text:
            log.debug("No text to analyze msg=%d", message.id)
            return result

        factors: list[tuple[str, int]] = []
        details: list[str] = []
        matched = 0
        compiled = gc.get_compiled_patterns()
        log.debug("Scanning %d patterns against msg=%d", len(compiled), message.id)

        for name, pattern, weight, enabled in compiled:
            if pattern.search(all_text):
                factors.append((name, weight))
                details.append(f"{name} ({weight})")
                matched += 1
                log.debug("Pattern hit msg=%d: '%s' (w=%d)", message.id, name, weight)

        log.debug("Pattern matches for msg=%d: %d/%d", message.id, matched, len(compiled))

        if not message.content.strip() and result["ocr_text"] and factors:
            bonus = gc.get("no_text_bonus", 10)
            factors.append(("no_text", bonus))
            details.append(f"no_text (+{bonus})")
            log.debug("No-text bonus +%d msg=%d", bonus, message.id)

        total = sum(w for _, w in factors)
        result["score"] = total
        result["factors"] = [f"{n} ({p})" for n, p in factors]

        score_alert = gc.get("score_alert", 50)
        score_warn = gc.get("score_warn", 30)

        if total >= score_alert:
            result["is_scam"] = True
            result["reason"] = f"Score {total}\n" + "\n".join(details)
            result["details"] = "\n".join(details)
            log.info("SCAM msg=%d score=%d/%d patterns=%d", message.id, total, score_alert, matched)
        elif total >= score_warn:
            result["reason"] = f"Score {total} (warning)"
            result["details"] = "\n".join(details)
            log.info("SUSPICIOUS msg=%d score=%d/%d", message.id, total, score_warn)
        else:
            result["reason"] = f"Score {total}"

        return result

    # ── Image helpers ────────────────────────────────────────────────

    async def _download(self, url: str, max_size: int = 5242880, timeout: int = 30) -> Optional[bytes]:
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    log.debug("Download HTTP %d: %s", resp.status, url)
                    return None
                data = await resp.read()
                if len(data) > max_size:
                    log.debug("Download oversized %d > %d: %s", len(data), max_size, url)
                    return None
                return data
        except asyncio.TimeoutError:
            log.debug("Download timeout %ds: %s", timeout, url)
            return None
        except aiohttp.ClientError as exc:
            log.debug("Download error %s: %s", url, exc)
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
        if urls:
            log.debug("Found %d image URLs in msg=%d", len(urls), msg.id)
        return urls
