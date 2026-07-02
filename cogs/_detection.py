"""Detection engine: OCR, image similarity, keyword scoring, user signals, URL checks."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiohttp
import discord
from core.ai_config import ai_config
from core.config import GuildConfig, config as global_cfg

log = logging.getLogger("cogs.detection")

_OCR_CACHE_DIR = Path("data/ocr_cache")
_MEMO_OCR: dict[str, str] = {}
# Cross-post tracker: {content_hash: [(channel_id, timestamp)]}
_crosspost: dict[str, list[tuple[int, float]]] = {}
# First-interaction tracker
_seen_users: set[int] = set()
# URL extraction regex
_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.I)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
# Domain age cache: domain -> (age_days, timestamp)
_domain_age_cache: dict[str, tuple[int | None, float]] = {}
_DOMAIN_CACHE_TTL = 3600
_DOMAIN_CACHE_MAX = 500
# Short URL resolution cache: short_url -> final_url
_resolve_cache: dict[str, str | None] = {}
_RESOLVE_TIMEOUT = 5
_RESOLVE_MAX_REDIRECTS = 5
_RESOLVE_CACHE_MAX = 1000
# Session persistence
_SESSION_DIR = Path("data/session")
_SEEN_USERS_MAX = 10000
_CROSSPOST_MAX = 1000
_MEMO_OCR_MAX = 500


def _ocr_cache_key(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ocr_cache_get(key: str) -> Optional[str]:
    text = _MEMO_OCR.get(key)
    if text is not None:
        return text
    path = _OCR_CACHE_DIR / f"{key}.txt"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        _MEMO_OCR[key] = text
        return text
    return None


def _ocr_cache_set(key: str, text: str) -> None:
    _MEMO_OCR[key] = text
    if len(_MEMO_OCR) > _MEMO_OCR_MAX:
        _MEMO_OCR.clear()
    _OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (_OCR_CACHE_DIR / f"{key}.txt").write_text(text, encoding="utf-8")


# ── Session persistence ────────────────────────────────────────────────

_SESSION_FILE = _SESSION_DIR / "session.json"


def _load_session() -> None:
    if not _SESSION_FILE.exists():
        return
    try:
        import json
        data = json.loads(_SESSION_FILE.read_text())
        _seen_users.update(data.get("seen_users", []))
        seen = data.get("crosspost", {})
        now = time.time()
        window = 300
        for h, entries in seen.items():
            fresh = [(cid, ts) for cid, ts in entries if now - ts < window]
            if fresh:
                _crosspost[h] = fresh
    except Exception:
        _SESSION_FILE.unlink(missing_ok=True)


def _save_session() -> None:
    import json
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    pruned_crosspost = {}
    for h, entries in _crosspost.items():
        if len(pruned_crosspost) >= _CROSSPOST_MAX:
            break
        pruned_crosspost[h] = entries
    if len(_seen_users) > _SEEN_USERS_MAX:
        _seen_users.clear()
    data = {
        "seen_users": list(_seen_users),
        "crosspost": pruned_crosspost,
    }
    _SESSION_FILE.write_text(json.dumps(data, ensure_ascii=False))


# ── Cache prune helpers ────────────────────────────────────────────────

def _prune_caches() -> None:
    now = time.time()
    # Domain age: clear expired
    _domain_age_cache.clear()
    # Resolve: cap size
    if len(_resolve_cache) > _RESOLVE_CACHE_MAX:
        _resolve_cache.clear()
    # OCR memo: cap size
    if len(_MEMO_OCR) > _MEMO_OCR_MAX:
        _MEMO_OCR.clear()
    # Crosspost: prune expired
    stale = [h for h, entries in _crosspost.items() if all(now - t > 3600 for _, t in entries)]
    for h in stale:
        del _crosspost[h]
    if len(_crosspost) > _CROSSPOST_MAX:
        _crosspost.clear()


class Detector:
    """OCR extraction, banned image matching, and weighted keyword scoring."""

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
            lang = global_cfg.get("language", ["fr", "en"])
            log.info("Initialising easyocr (CPU, %s) ...", "+".join(lang))
            self._ocr = easyocr.Reader(lang, gpu=False)
            log.info("easyocr ready")
        return self._ocr

    async def preload_ocr(self) -> None:
        await self.bot.loop.run_in_executor(None, lambda: self.ocr)

    async def _ocr_bytes(self, data: bytes, max_ocr_len: int = 2000) -> Optional[str]:
        k = _ocr_cache_key(data)
        cached = _ocr_cache_get(k)
        if cached is not None:
            log.debug("OCR cache hit (%d chars)", len(cached))
            return cached[:max_ocr_len]

        async with self._ocr_sem:
            log.debug("Running OCR on %d bytes ...", len(data))
            try:
                results = await self.bot.loop.run_in_executor(None, self._run_ocr, io.BytesIO(data))
                if results:
                    text = " ".join(r[1] for r in results)
                    _ocr_cache_set(k, text)
                    log.debug("OCR extracted %d chars (cached)", len(text))
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
        self._banned_hashes_cache = None

    def _banned_hashes(self, gc: GuildConfig):
        attr = "_banned_hashes_cache"
        cached = getattr(self, attr, None)
        if cached is not None:
            return cached
        hashes: list = []
        banned_dir = gc.get("banned_images_dir", "banned_images")
        p = Path(banned_dir)
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

    # ── Image helpers ────────────────────────────────────────────────

    async def _download(self, url: str, max_size: int = 5242880, timeout: int = 30) -> Optional[bytes]:
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                if len(data) > max_size:
                    return None
                return data
        except (asyncio.TimeoutError, aiohttp.ClientError):
            return None

    async def _get_image_urls(self, msg: discord.Message, gc: GuildConfig) -> list[str]:
        exts = tuple(gc.get("supported_extensions", [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]))
        urls = list(dict.fromkeys(a.url for a in msg.attachments if any(a.filename.lower().endswith(e) for e in exts)))
        for e in msg.embeds:
            if e.image and e.image.url and e.image.url not in urls:
                urls.append(e.image.url)
            if e.thumbnail and e.thumbnail.url and e.thumbnail.url not in urls:
                urls.append(e.thumbnail.url)
        if msg.content:
            img_re = gc.get("image_url_regex", r"(https?://[^\s]+\.(?:png|jpg|jpeg|gif|webp))")
            import re
            for m in re.finditer(img_re, msg.content, re.I):
                if m.group(1) not in urls:
                    urls.append(m.group(1))
        return urls

    # ── URL reputation ────────────────────────────────────────────────

    async def _check_urls(self, message: discord.Message, gc: GuildConfig) -> list[tuple[str, int]]:
        """Check URLs for suspicious patterns, resolve shorteners, check domain age."""
        factors: list[tuple[str, int]] = []
        if not message.content.strip():
            return factors

        urls = _URL_RE.findall(message.content)
        if not urls:
            return factors

        whitelisted = gc.get_whitelisted_domains()
        shorteners = gc.get("url_shorteners", [])
        suspect_tlds = gc.get("suspect_tlds", [])
        max_total = gc.get("url_max_score", 50)
        new_domain_days = gc.get("url_new_domain_days", 30)
        seen_domains: set[str] = set()

        for url in urls[:5]:
            try:
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                if ":" in domain:
                    domain = domain.split(":")[0]
                if domain.startswith("www."):
                    domain = domain[4:]
                if not domain:
                    continue
                if domain in seen_domains:
                    continue
                seen_domains.add(domain)
                if domain in whitelisted:
                    continue

                total = sum(s for _, s in factors)
                is_shortener = domain in shorteners

                # URL shortener → resolve redirect, check final domain
                if is_shortener:
                    score = gc.get("url_shortener_score", 15)
                    if score and total < max_total:
                        factors.append((f"url_shortener_{domain}", score))
                        total += score
                        log.debug("URL: shortener %s (+%d)", domain, score)

                    final_url = await self._resolve_short_url(url)
                    if final_url:
                        final_parsed = urlparse(final_url)
                        final_domain = final_parsed.netloc.lower()
                        if ":" in final_domain:
                            final_domain = final_domain.split(":")[0]
                        if final_domain.startswith("www."):
                            final_domain = final_domain[4:]
                        if final_domain and final_domain != domain and final_domain not in seen_domains:
                            seen_domains.add(final_domain)
                            if final_domain in whitelisted:
                                continue
                            f_total = sum(s for _, s in factors)
                            await self._analyze_domain(final_domain, factors, f_total, gc, suspect_tlds, max_total, new_domain_days)
                    continue

                # Domain checks (IP, TLD, age)
                await self._analyze_domain(domain, factors, sum(s for _, s in factors), gc, suspect_tlds, max_total, new_domain_days)

            except Exception:
                log.debug("URL check failed for %s", url, exc_info=True)

        return factors

    async def _analyze_domain(self, domain: str, factors: list, total: int, gc, suspect_tlds: list, max_total: int, new_domain_days: int) -> None:
        """Apply domain-level checks (IP, TLD, age) to a domain."""
        # IP-based
        score = gc.get("url_ip_score", 20)
        if score and total < max_total:
            try:
                import ipaddress
                ipaddress.ip_address(domain)
                factors.append((f"url_ip_{domain}", score))
                total += score
                log.debug("URL: IP-based domain %s (+%d)", domain, score)
            except ValueError:
                pass

        # Suspicious TLD
        score = gc.get("url_suspect_tld_score", 10)
        if score and total < max_total:
            for tld in suspect_tlds:
                if domain.endswith(tld):
                    factors.append((f"url_tld_{tld}", score))
                    total += score
                    log.debug("URL: suspect TLD %s (%s) (+%d)", domain, tld, score)
                    break

        # Domain age
        score = gc.get("url_new_domain_score", 25)
        if score and total < max_total:
            age = await self._get_domain_age(domain)
            if age is not None and age < new_domain_days:
                factors.append((f"url_new_domain_{domain}_{age}d", score))
                log.debug("URL: new domain %s %dd (+%d)", domain, age, score)

    async def _resolve_short_url(self, url: str) -> str | None:
        """Follow redirects to resolve a shortened URL. Returns final URL or None."""
        cached = _resolve_cache.get(url)
        if cached is not None:
            return cached if cached else None

        try:
            async with self.session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=_RESOLVE_TIMEOUT),
                allow_redirects=True,
                max_redirects=_RESOLVE_MAX_REDIRECTS,
            ) as resp:
                final = str(resp.url)
                _resolve_cache[url] = final if final != url else None
                return _resolve_cache[url]
        except Exception:
            log.debug("URL resolve failed for %s", url)
            _resolve_cache[url] = None
            return None

    async def _get_domain_age(self, domain: str) -> int | None:
        """Return domain age in days, from cache or whois. Returns None on failure."""
        now = time.time()
        cached = _domain_age_cache.get(domain)
        if cached and now - cached[1] < _DOMAIN_CACHE_TTL:
            return cached[0]

        try:
            import whois
            w = await self.bot.loop.run_in_executor(None, lambda: whois.whois(domain))
            creation = w.creation_date
            if isinstance(creation, list):
                creation = creation[0]
            if creation:
                import datetime
                if isinstance(creation, datetime.datetime):
                    age = (discord.utils.utcnow() - creation).days
                    _domain_age_cache[domain] = (age, now)
                    return age
        except Exception:
            _domain_age_cache[domain] = (None, now)
            log.debug("whois lookup failed for %s", domain)
        return None

    # ── User signals ──────────────────────────────────────────────────

    def _compute_user_signals(self, message: discord.Message, gc: GuildConfig, has_urls: bool) -> list[tuple[str, int]]:
        """Compute behavioural signals about the user/message for bonus score."""
        signals: list[tuple[str, int]] = []
        now = discord.utils.utcnow()

        # Account age
        min_days = gc.get("signal_account_age_days", 30)
        score = gc.get("signal_account_age_score", 15)
        if score and min_days:
            age = (now - message.author.created_at).days
            if age < min_days:
                signals.append((f"account_age_{age}d", score))
                log.debug("Signal: account age %dd < %dd (+%d) uid=%d", age, min_days, score, message.author.id)

        # Server join age
        min_days = gc.get("signal_join_age_days", 7)
        score = gc.get("signal_join_age_score", 15)
        if score and min_days and message.author.joined_at:
            age = (now - message.author.joined_at).days
            if age < min_days:
                signals.append((f"join_age_{age}d", score))
                log.debug("Signal: join age %dd < %dd (+%d) uid=%d", age, min_days, score, message.author.id)

        # First interaction
        score = gc.get("signal_first_interaction_score", 10)
        if score and message.author.id not in _seen_users:
            _seen_users.add(message.author.id)
            signals.append(("first_interaction", score))
            log.debug("Signal: first interaction (+%d) uid=%d", score, message.author.id)

        # Image/URL-only (no author text)
        score = gc.get("signal_image_only_score", 10)
        if score and has_urls and not message.content.strip():
            signals.append(("image_only", score))
            log.debug("Signal: image only (+%d) uid=%d", score, message.author.id)

        # Default avatar
        score = gc.get("signal_no_avatar_score", 5)
        if score and message.author.avatar is None:
            signals.append(("no_avatar", score))
            log.debug("Signal: no avatar (+%d) uid=%d", score, message.author.id)

        # Cross-posting detection
        score_pp = gc.get("signal_crosspost_score", 20)
        window = gc.get("signal_crosspost_window", 300)
        min_ch = gc.get("signal_crosspost_min_channels", 2)
        if score_pp and window and message.content.strip():
            h = hashlib.sha256(message.content.strip().lower().encode()).hexdigest()[:16]
            ts = time.time()
            entries = _crosspost.setdefault(h, [])
            # Prune old
            entries[:] = [(cid, t) for cid, t in entries if ts - t < window]
            entries.append((message.channel.id, ts))
            unique = len({cid for cid, _ in entries})
            if unique >= min_ch:
                signals.append((f"crosspost_{unique}ch", score_pp))
                log.debug("Signal: crosspost %d channels (+%d) uid=%d", unique, score_pp, message.author.id)

        return signals

    # ── AI multimodal ─────────────────────────────────────────────────

    async def _ai_check(self, text: str, gc: GuildConfig) -> int | None:
        """Optional AI second opinion via litellm routing. Returns bonus score or None."""
        if not gc.get("ai_enabled", False):
            return None
        model_name = gc.get("ai_model", "gpt-4o-mini")
        bonus = gc.get("ai_score_bonus", 30)
        mc, pc, prompt = ai_config.resolve_model(model_name)
        if not mc or not pc:
            log.debug("AI: model '%s' or its provider not found in config", model_name)
            return None

        import os
        api_key = os.environ.get(pc.env_key)
        if not api_key:
            log.debug("AI: env var '%s' not set for provider '%s'", pc.env_key, mc.provider)
            return None

        try:
            import litellm
            import json as _json
            litellm_model = f"{mc.provider}/{mc.model}"

            if mc.endpoint_type == "moderations":
                kwargs = dict(model=mc.model, input=text[:2000], api_key=api_key)
                if mc.provider != "anthropic":
                    kwargs["api_base"] = pc.endpoint
                resp = await litellm.amoderation(**kwargs)
                if resp.results and resp.results[0].flagged:
                    log.info("AI flagged scam (moderation)")
                    return bonus
                return None

            kwargs = dict(model=litellm_model, api_key=api_key, temperature=0, max_tokens=100)
            if mc.provider != "anthropic":
                kwargs["api_base"] = pc.endpoint
            if mc.endpoint_type == "messages":
                kwargs["messages"] = [{"role": "user", "content": text[:2000]}]
                if prompt:
                    kwargs["system"] = prompt
            else:
                kwargs["messages"] = [{"role": "system", "content": prompt}, {"role": "user", "content": text[:2000]}]

            resp = await litellm.acompletion(**kwargs)
            raw = resp.choices[0].message.content
            if not raw:
                return None
            m = _JSON_RE.search(raw)
            if m:
                raw = m.group(0)
            parsed = _json.loads(raw)
            if parsed.get("scam"):
                log.info("AI flagged scam: %s", parsed.get("reason", ""))
                return bonus
        except Exception:
            log.debug("AI check failed", exc_info=True)
        return None

    # ── Main analysis ────────────────────────────────────────────────

    async def analyze_message(self, message: discord.Message, gc: GuildConfig) -> dict:
        """Score message against guild keywords + OCR + banned image check."""
        result = {"is_scam": False, "score": 0, "reason": "", "details": "", "ocr_text": "", "images": [], "factors": [], "image_flag": None}

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
                    return url, await self._download(url, max_size, dl_timeout)

            downloaded = await asyncio.gather(*[_dl(u) for u in urls])
            # OCR in parallel
            ocr_tasks = [self._ocr_bytes(d, ocr_max) for _, d in downloaded if d is not None]
            ocr_results = await asyncio.gather(*ocr_tasks) if ocr_tasks else []
            for text in ocr_results:
                if text:
                    result["ocr_text"] += text + "\n"
                    all_text += text + "\n"

            # Banned image check in parallel
            banned_tasks = [self.check_banned_image(d, gc) for _, d in downloaded if d is not None]
            banned_results = [m for m in await asyncio.gather(*banned_tasks) if m]
            if banned_results:
                match = banned_results[0]
                result["image_flag"] = {"banned": match}
                banned_score = int(gc.get("banned_images_score", 50))
                result["score"] += banned_score
                result.setdefault("factors", []).append(
                    f"banned_image ({match['matched']}, {match['similarity']}%)"
                )
                log.warning("Banned image msg=%d matched=%s sim=%s", message.id, match["matched"], match["similarity"])

        all_text = all_text.strip()
        if not all_text:
            return result

        # Keyword matching (case-insensitive substring)
        all_lower = all_text.lower()
        factors: list[tuple[str, int]] = []
        details: list[str] = []
        matched = 0

        compiled = gc.get_compiled_keywords()
        for word, weight, desc in compiled:
            if word in all_lower:
                factors.append((word.replace(" ", "_"), weight))
                details.append(f"{word} ({weight})")
                matched += 1
                log.debug("Keyword hit msg=%d: '%s' (w=%d)", message.id, word, weight)

        log.debug("Keyword matches for msg=%d: %d/%d", message.id, matched, len(compiled))

        if not message.content.strip() and result["ocr_text"] and factors:
            bonus = gc.get("no_text_bonus", 10)
            factors.append(("no_text", bonus))
            details.append(f"no_text (+{bonus})")

        # User behavioural signals
        user_signals = self._compute_user_signals(message, gc, bool(urls))
        for name, s in user_signals:
            factors.append((name, s))
            details.append(f"{name} (+{s})")

        # URL reputation checks
        url_factors = await self._check_urls(message, gc)
        for name, s in url_factors:
            factors.append((name, s))
            details.append(f"{name} (+{s})")

        # AI second opinion (optional)
        if all_text:
            ai_bonus = await self._ai_check(all_text, gc)
            if ai_bonus:
                factors.append(("ai_verdict", ai_bonus))
                details.append(f"ai_verdict (+{ai_bonus})")

        total = result["score"] + sum(w for _, w in factors)
        result["score"] = total
        result["factors"].extend(f"{n} ({p})" for n, p in factors)

        score_alert = gc.get("score_alert", 50)
        score_warn = gc.get("score_warn", 30)

        if total >= score_alert:
            result["is_scam"] = True
            result["reason"] = f"Score {total}\n" + "\n".join(details)
            result["details"] = "\n".join(details)
            log.info("SCAM msg=%d score=%d/%d keywords=%d", message.id, total, score_alert, matched)
        elif total >= score_warn:
            result["reason"] = f"Score {total} (warning)"
            result["details"] = "\n".join(details)
        else:
            result["reason"] = f"Score {total}"

        return result
