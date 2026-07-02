"""Per-guild configuration with version history and rollback."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from bot import config as global_cfg

log = logging.getLogger("core.guild_config")

DATA_DIR = Path("data/guilds")


def _load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class VersionManager:
    """Stores and manages config versions for rollback."""

    MAX_VERSIONS = 30

    def __init__(self, guild_config: GuildConfig) -> None:
        self.gc = guild_config
        self._path = DATA_DIR / f"{guild_config.guild_id}.versions.json"

    def _load(self) -> list:
        data = _load_json(self._path)
        return data if isinstance(data, list) else []

    def _save(self, versions: list) -> None:
        _save_json(self._path, versions)

    def snapshot(self) -> None:
        """Save current config as a version snapshot."""
        versions = self._load()
        entry = {
            "version": self.gc.data.get("_version", 0),
            "timestamp": time.time(),
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "config": self.gc.data,
        }
        versions.append(entry)
        if len(versions) > self.MAX_VERSIONS:
            versions = versions[-self.MAX_VERSIONS:]
        self._save(versions)
        log.debug("Version %d saved for guild %d", entry["version"], self.gc.guild_id)

    def list(self, limit: int = 10) -> list[dict]:
        """Return last N versions metadata."""
        versions = self._load()
        return [
            {"version": v["version"], "date": v.get("date", "")}
            for v in versions[-limit:]
        ]

    def revert(self, version: int) -> bool:
        """Restore guild config to given version. Returns False if not found."""
        versions = self._load()
        for v in versions:
            if v["version"] == version:
                self.snapshot()
                self.gc.data = dict(v["config"])
                self.gc.data["_version"] = self.gc.data.get("_version", 0) + 1
                self.gc.data["_reverted_to"] = version
                self.gc._save()
                self.gc._invalidate_cache()
                log.warning("Guild %d reverted to version %d", self.gc.guild_id, version)
                return True
        return False


class GuildConfig:
    """Per-guild configuration, falling back to global defaults."""

    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        self.data: dict = {}
        self._compiled_patterns: list | None = None
        self._load()

    def _path(self) -> Path:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return DATA_DIR / f"{self.guild_id}.json"

    def _load(self) -> None:
        data = _load_json(self._path())
        if data:
            self.data = data
        else:
            self.data = {
                "guild_id": self.guild_id,
                "_version": 0,
                "settings": {},
                "patterns": [],
                "actions": {"scam": [], "suspicious": [], "banned_image": []},
                "ignored": {"user_ids": [], "role_ids": [], "channel_ids": []},
            }

    def _save(self) -> None:
        _save_json(self._path(), self.data)

    def _invalidate_cache(self) -> None:
        self._compiled_patterns = None

    # ── Settings ─────────────────────────────────────────────────────

    def get(self, key: str, default=None):
        """Get a setting: guild-specific takes priority, fallback to global."""
        val = self.data.get("settings", {}).get(key)
        if val is not None:
            return val
        return global_cfg.get(key, default)

    def set(self, key: str, value) -> None:
        if key == "actions":
            return
        vm = VersionManager(self)
        vm.snapshot()
        self.data.setdefault("settings", {})[key] = value
        self.data["_version"] = self.data.get("_version", 0) + 1
        self._save()

    # ── Actions ──────────────────────────────────────────────────────

    def get_actions(self, trigger: str) -> list:
        return self.data.get("actions", {}).get(trigger, [])

    def add_action(self, trigger: str, action: dict) -> None:
        VersionManager(self).snapshot()
        self.data.setdefault("actions", {}).setdefault(trigger, []).append(action)
        self.data["_version"] = self.data.get("_version", 0) + 1
        self._save()

    def remove_action(self, trigger: str, index: int) -> bool:
        actions = self.data.get("actions", {}).get(trigger, [])
        if not 0 <= index < len(actions):
            return False
        VersionManager(self).snapshot()
        actions.pop(index)
        self.data["_version"] = self.data.get("_version", 0) + 1
        self._save()
        return True

    def clear_actions(self, trigger: str) -> None:
        VersionManager(self).snapshot()
        self.data.setdefault("actions", {})[trigger] = []
        self.data["_version"] = self.data.get("_version", 0) + 1
        self._save()

    # ── Patterns ─────────────────────────────────────────────────────

    def get_patterns(self) -> list:
        """Return guild-specific patterns or fallback to global."""
        if self.data.get("patterns"):
            return self.data["patterns"]
        return global_cfg.raw_patterns

    def get_compiled_patterns(self) -> list[tuple[str, re.Pattern, int, bool]]:
        """Return compiled patterns (cached)."""
        if self._compiled_patterns is not None:
            return self._compiled_patterns
        compiled = []
        for p in self.get_patterns():
            if not p.get("enabled", True):
                continue
            try:
                compiled.append((p["name"], re.compile(p["pattern"], re.I), p["weight"], True))
            except re.error as exc:
                log.error("Regex error for '%s': %s", p["name"], exc)
        self._compiled_patterns = compiled
        return compiled

    def add_pattern(self, name: str, pattern: str, weight: int, desc: str = "") -> bool:
        for p in self.data.get("patterns", []):
            if p["name"] == name:
                return False
        VersionManager(self).snapshot()
        entry = {"name": name, "pattern": pattern, "weight": weight, "enabled": True, "desc": desc or name}
        self.data.setdefault("patterns", []).append(entry)
        self.data["_version"] = self.data.get("_version", 0) + 1
        self._invalidate_cache()
        self._save()
        return True

    def remove_pattern(self, name: str) -> bool:
        for i, p in enumerate(self.data.get("patterns", [])):
            if p["name"] == name:
                VersionManager(self).snapshot()
                self.data["patterns"].pop(i)
                self.data["_version"] += 1
                self._invalidate_cache()
                self._save()
                return True
        return False

    def toggle_pattern(self, name: str) -> bool | None:
        for p in self.data.get("patterns", []):
            if p["name"] == name:
                VersionManager(self).snapshot()
                p["enabled"] = not p.get("enabled", True)
                self.data["_version"] += 1
                self._invalidate_cache()
                self._save()
                return p["enabled"]
        # Copy global pattern to guild before toggle (no cross-guild mutation)
        for p in global_cfg.raw_patterns:
            if p["name"] == name:
                VersionManager(self).snapshot()
                entry = dict(p)
                entry["enabled"] = not entry.get("enabled", True)
                self.data.setdefault("patterns", []).append(entry)
                self.data["_version"] += 1
                self._invalidate_cache()
                self._save()
                return entry["enabled"]
        return None

    # ── Ignored entities ─────────────────────────────────────────────

    def get_ignored(self, key: str) -> list:
        return self.data.get("ignored", {}).get(key, [])

    def toggle_ignored(self, target: str, entity_id: int, action: str) -> bool:
        key_map = {"user": "user_ids", "role": "role_ids", "channel": "channel_ids"}
        key = key_map.get(target)
        if not key:
            return False
        lst = list(self.get_ignored(key))
        if action == "add":
            if entity_id in lst:
                return False
            VersionManager(self).snapshot()
            lst.append(entity_id)
            self.data.setdefault("ignored", {})[key] = lst
            self.data["_version"] += 1
            self._save()
            return True
        else:
            if entity_id not in lst:
                return False
            VersionManager(self).snapshot()
            lst.remove(entity_id)
            self.data.setdefault("ignored", {})[key] = lst
            self.data["_version"] += 1
            self._save()
            return True

    # ── Utility ──────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset guild config to defaults, preserving guild_id."""
        VersionManager(self).snapshot()
        self.data = {
            "guild_id": self.guild_id,
            "_version": self.data.get("_version", 0) + 1,
            "settings": {},
            "patterns": [],
            "actions": {"scam": [], "suspicious": [], "banned_image": []},
            "ignored": {"user_ids": [], "role_ids": [], "channel_ids": []},
        }
        self._invalidate_cache()
        self._save()

    def __repr__(self) -> str:
        return f"<GuildConfig id={self.guild_id} v={self.data.get('_version', 0)} pat={len(self.get_patterns())}>"

    def to_dict(self) -> dict:
        return {
            "settings": self.data.get("settings", {}),
            "patterns": len(self.get_patterns()),
            "actions": {t: len(a) for t, a in self.data.get("actions", {}).items()},
            "ignored": {k: len(v) for k, v in self.data.get("ignored", {}).items()},
            "version": self.data.get("_version", 0),
        }


# ── Guild config registry ─────────────────────────────────────────────

_guild_configs: dict[int, GuildConfig] = {}


def get_guild_config(guild_id: int) -> GuildConfig:
    """Get or create cached guild config."""
    if guild_id not in _guild_configs:
        _guild_configs[guild_id] = GuildConfig(guild_id)
    return _guild_configs[guild_id]


def remove_guild_config(guild_id: int) -> None:
    """Remove a guild from the config cache (e.g. on guild leave)."""
    _guild_configs.pop(guild_id, None)


def clear_guild_config_cache() -> None:
    _guild_configs.clear()
