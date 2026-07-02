"""Per-guild detection stats with JSON persistence."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("core.stats")

STATS_DIR = Path("data/stats")


_FLUSH_DEBOUNCE = 10


class StatsManager:
    """Tracks and persists detection statistics per guild."""

    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        self.data: dict = self._load()
        self._last_flush = 0.0
        self._dirty = False

    def _path(self) -> Path:
        STATS_DIR.mkdir(parents=True, exist_ok=True)
        return STATS_DIR / f"{self.guild_id}.json"

    def _load(self) -> dict:
        p = self._path()
        if p.exists():
            try:
                with open(p) as f:
                    return json.load(f)
            except Exception:
                log.warning("Corrupted stats file %s, resetting", p)
        return {
            "guild_id": self.guild_id,
            "first_seen": int(time.time()),
            "total_scanned": 0,
            "scam_detected": 0,
            "suspicious_detected": 0,
            "banned_images": 0,
            "actions_taken": 0,
        }

    def _save(self) -> None:
        with open(self._path(), "w") as f:
            json.dump(self.data, f, indent=2)

    def _mark_dirty(self) -> None:
        self._dirty = True
        now = time.time()
        if now - self._last_flush >= _FLUSH_DEBOUNCE:
            self._save()
            self._last_flush = now
            self._dirty = False

    def increment_scanned(self) -> None:
        self.data["total_scanned"] += 1
        self._mark_dirty()

    def increment_scam(self) -> None:
        self.data["scam_detected"] += 1
        self._mark_dirty()

    def increment_suspicious(self) -> None:
        self.data["suspicious_detected"] += 1
        self._mark_dirty()

    def increment_banned_image(self) -> None:
        self.data["banned_images"] += 1
        self._mark_dirty()

    def increment_actions(self) -> None:
        self.data["actions_taken"] += 1
        self._mark_dirty()

    def flush(self) -> None:
        if self._dirty:
            self._save()
            self._last_flush = time.time()
            self._dirty = False

    def summary(self) -> str:
        fields = (
            ("Total scanned", self.data["total_scanned"]),
            ("Scams detected", self.data["scam_detected"]),
            ("Suspicious flagged", self.data["suspicious_detected"]),
            ("Banned images", self.data["banned_images"]),
            ("Actions taken", self.data["actions_taken"]),
        )
        return "\n".join(f"- **{k}:** {v}" for k, v in fields)


_stats_cache: dict[int, StatsManager] = {}


def get_stats(guild_id: int) -> StatsManager:
    if guild_id not in _stats_cache:
        _stats_cache[guild_id] = StatsManager(guild_id)
    return _stats_cache[guild_id]


def flush_all() -> None:
    for sm in _stats_cache.values():
        sm._dirty = True
        sm.flush()
