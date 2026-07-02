"""Global + per-guild config with keywords support and version history."""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

log = logging.getLogger("core.config")

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


_DEFAULT_KEYWORDS = [
    {"word": "seed phrase", "weight": 50, "desc": "Seed phrase theft", "enabled": True},
    {"word": "private key", "weight": 50, "desc": "Private key theft", "enabled": True},
    {"word": "cle privee", "weight": 50, "desc": "Vol de cle privee", "enabled": True},
    {"word": "passphrase", "weight": 50, "desc": "Passphrase recovery scam", "enabled": True},
    {"word": "verify wallet", "weight": 50, "desc": "Wallet verification scam", "enabled": True},
    {"word": "validate wallet", "weight": 50, "desc": "Wallet validation scam", "enabled": True},
    {"word": "synchronize wallet", "weight": 50, "desc": "Wallet sync scam", "enabled": True},
    {"word": "double your crypto", "weight": 35, "desc": "Promise to double crypto", "enabled": True},
    {"word": "doublez vos", "weight": 35, "desc": "Promesse de doubler crypto", "enabled": True},
    {"word": "crypto casino", "weight": 35, "desc": "Crypto casino/gambling", "enabled": True},
    {"word": "free eth", "weight": 30, "desc": "Free ETH giveaway", "enabled": True},
    {"word": "free bitcoin", "weight": 30, "desc": "Free BTC giveaway", "enabled": True},
    {"word": "free crypto", "weight": 25, "desc": "Free crypto scam", "enabled": True},
    {"word": "elon musk", "weight": 30, "desc": "Celebrity impersonation", "enabled": True},
    {"word": "airdrop", "weight": 25, "desc": "Airdrop/claim", "enabled": True},
    {"word": "claim free", "weight": 25, "desc": "Fake airdrop claim", "enabled": True},
    {"word": "giveaway", "weight": 25, "desc": "Fake giveaway", "enabled": True},
    {"word": "metamask", "weight": 20, "desc": "Wallet mention (combinatorial)", "enabled": True},
    {"word": "trust wallet", "weight": 20, "desc": "Trust wallet scam", "enabled": True},
    {"word": "phantom wallet", "weight": 20, "desc": "Phantom wallet scam", "enabled": True},
    {"word": "invest in crypto", "weight": 20, "desc": "Fake investment", "enabled": True},
    {"word": "investir dans", "weight": 20, "desc": "Fausse opportunite", "enabled": True},
    {"word": "presale", "weight": 10, "desc": "Presale/whitelist", "enabled": True},
    {"word": "whitelist", "weight": 10, "desc": "Whitelist access", "enabled": True},
    {"word": "withdraw your", "weight": 10, "desc": "Withdrawal pressure", "enabled": True},
    {"word": "urgent", "weight": 5, "desc": "Urgency (combinatorial)", "enabled": True},
    {"word": "limited time", "weight": 5, "desc": "Time pressure (combinatorial)", "enabled": True},
    {"word": "act now", "weight": 5, "desc": "Act now pressure", "enabled": True},
    {"word": "bonus", "weight": 5, "desc": "Bonus offer (combinatorial)", "enabled": True},
    {"word": "follow me", "weight": 5, "desc": "Follow-for-giveaway (combinatorial)", "enabled": True},
]


# ── ConfigManager ───────────────────────────────────────────────────────

class ConfigManager:
    """Loads and centralises configuration from the config/ directory."""

    def __init__(self, config_dir: str = "config") -> None:
        self._dir = Path(config_dir)
        self._keywords: list[dict] = []
        self.settings: dict = {}
        self._loaded = False

    def _load_json(self, path: Path) -> dict:
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return {}

    def _save_json(self, path: Path, data: dict) -> None:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log.info("Saved %s", path.name)

    def load(self) -> None:
        kw_path = self._dir / "keywords.json"
        settings_path = self._dir / "settings.json"

        old = self._dir / "patterns.json"
        if old.exists() and not kw_path.exists():
            shutil.copy(old, old.with_suffix(".json.legacy"))
            self._save_json(kw_path, {"keywords": _DEFAULT_KEYWORDS})
            log.warning("Migrated old patterns -> keywords (backup: patterns.json.legacy)")

        data = self._load_json(kw_path)
        self._keywords = data.get("keywords", [])
        self.settings = self._load_json(settings_path)
        self._loaded = True
        log.info("Config loaded: %d keywords, %d settings", len(self._keywords), len(self.settings))

    @property
    def keywords(self) -> list[dict]:
        if not self._loaded:
            self.load()
        return self._keywords

    @property
    def raw_keywords(self) -> list[dict]:
        return self.keywords

    def get(self, key: str, default=None):
        if not self._loaded:
            self.load()
        return self.settings.get(key, default)

    def reload(self) -> None:
        self._loaded = False
        self.load()

    def set_setting(self, key: str, value) -> None:
        if key == "actions":
            return
        self.settings[key] = value
        self._save_json(self._dir / "settings.json", self.settings)

    def get_actions(self, trigger: str) -> list:
        return self.settings.get("actions", {}).get(trigger, [])

    def add_action(self, trigger: str, action: dict) -> None:
        actions = self.settings.setdefault("actions", {})
        actions.setdefault(trigger, []).append(action)
        self._save_json(self._dir / "settings.json", self.settings)

    def remove_action(self, trigger: str, index: int) -> bool:
        actions = self.settings.get("actions", {}).get(trigger, [])
        if 0 <= index < len(actions):
            actions.pop(index)
            self._save_json(self._dir / "settings.json", self.settings)
            return True
        return False

    def clear_actions(self, trigger: str) -> None:
        actions = self.settings.setdefault("actions", {})
        actions[trigger] = []
        self._save_json(self._dir / "settings.json", self.settings)

    def add_keyword(self, word: str, weight: int, desc: str = "") -> bool:
        for k in self._keywords:
            if k["word"] == word:
                return False
        self._keywords.append({"word": word, "weight": weight, "enabled": True, "desc": desc or word})
        self._save_json(self._dir / "keywords.json", {"keywords": self._keywords})
        return True

    def remove_keyword(self, word: str) -> bool:
        for i, k in enumerate(self._keywords):
            if k["word"] == word:
                self._keywords.pop(i)
                self._save_json(self._dir / "keywords.json", {"keywords": self._keywords})
                return True
        return False

    def toggle_keyword(self, word: str) -> bool | None:
        for k in self._keywords:
            if k["word"] == word:
                k["enabled"] = not k.get("enabled", True)
                self._save_json(self._dir / "keywords.json", {"keywords": self._keywords})
                return k["enabled"]
        return None


config = ConfigManager()


# ── VersionManager ──────────────────────────────────────────────────────

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

    def list(self, limit: int = 10) -> list[dict]:
        versions = self._load()
        return [{"version": v["version"], "date": v.get("date", "")} for v in versions[-limit:]]

    def revert(self, version: int) -> bool:
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


# ── GuildConfig ─────────────────────────────────────────────────────────

class GuildConfig:
    """Per-guild configuration, falling back to global defaults."""

    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        self.data: dict = {}
        self._compiled_keywords: list | None = None
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
                "keywords": [],
                "actions": {"scam": [], "suspicious": [], "banned_image": []},
                "ignored": {"user_ids": [], "role_ids": [], "channel_ids": []},
            }

    def _save(self) -> None:
        _save_json(self._path(), self.data)

    def _invalidate_cache(self) -> None:
        self._compiled_keywords = None

    def get(self, key: str, default=None):
        val = self.data.get("settings", {}).get(key)
        if val is not None:
            return val
        return config.get(key, default)

    def set(self, key: str, value) -> None:
        if key == "actions":
            return
        VersionManager(self).snapshot()
        self.data.setdefault("settings", {})[key] = value
        self.data["_version"] = self.data.get("_version", 0) + 1
        self._save()

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

    def get_keywords(self) -> list[dict]:
        if self.data.get("keywords"):
            return self.data["keywords"]
        return config.raw_keywords

    def get_compiled_keywords(self) -> list[tuple[str, int, str]]:
        if self._compiled_keywords is not None:
            return self._compiled_keywords
        compiled = []
        for k in self.get_keywords():
            if not k.get("enabled", True):
                continue
            compiled.append((k["word"], k["weight"], k.get("desc", "")))
        self._compiled_keywords = compiled
        return compiled

    def add_keyword(self, word: str, weight: int, desc: str = "") -> bool:
        for k in self.data.get("keywords", []):
            if k["word"] == word:
                return False
        VersionManager(self).snapshot()
        self.data.setdefault("keywords", []).append(
            {"word": word, "weight": weight, "enabled": True, "desc": desc or word}
        )
        self.data["_version"] = self.data.get("_version", 0) + 1
        self._invalidate_cache()
        self._save()
        return True

    def remove_keyword(self, word: str) -> bool:
        for i, k in enumerate(self.data.get("keywords", [])):
            if k["word"] == word:
                VersionManager(self).snapshot()
                self.data["keywords"].pop(i)
                self.data["_version"] += 1
                self._invalidate_cache()
                self._save()
                return True
        return False

    def toggle_keyword(self, word: str) -> bool | None:
        for k in self.data.get("keywords", []):
            if k["word"] == word:
                VersionManager(self).snapshot()
                k["enabled"] = not k.get("enabled", True)
                self.data["_version"] += 1
                self._invalidate_cache()
                self._save()
                return k["enabled"]
        for k in config.raw_keywords:
            if k["word"] == word:
                VersionManager(self).snapshot()
                entry = dict(k)
                entry["enabled"] = not entry.get("enabled", True)
                self.data.setdefault("keywords", []).append(entry)
                self.data["_version"] += 1
                self._invalidate_cache()
                self._save()
                return entry["enabled"]
        return None

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
        if entity_id not in lst:
            return False
        VersionManager(self).snapshot()
        lst.remove(entity_id)
        self.data.setdefault("ignored", {})[key] = lst
        self.data["_version"] += 1
        self._save()
        return True

    def batch_apply(self, **changes) -> None:
        from copy import deepcopy
        prev = deepcopy(self.data)
        for key, value in changes.items():
            if key == "settings" and isinstance(value, dict):
                self.data.setdefault("settings", {}).update(value)
            elif key == "actions" and isinstance(value, dict):
                self.data["actions"] = {
                    "scam": value.get("scam", []),
                    "suspicious": value.get("suspicious", []),
                    "banned_image": value.get("banned_image", []),
                }
            elif key == "keywords" and isinstance(value, list):
                self.data["keywords"] = value
            elif key == "reset" and value:
                self.data = {
                    "guild_id": self.guild_id,
                    "_version": self.data.get("_version", 0) + 1,
                    "settings": {},
                    "keywords": [],
                    "actions": {"scam": [], "suspicious": [], "banned_image": []},
                    "ignored": {"user_ids": [], "role_ids": [], "channel_ids": []},
                }
                self._invalidate_cache()
                self._save()
                return
        if self.data != prev:
            VersionManager(self).snapshot()
            self.data["_version"] = self.data.get("_version", 0) + 1
            self._invalidate_cache()
            self._save()

    def reset(self) -> None:
        VersionManager(self).snapshot()
        self.data = {
            "guild_id": self.guild_id,
            "_version": self.data.get("_version", 0) + 1,
            "settings": {},
            "keywords": [],
            "actions": {"scam": [], "suspicious": [], "banned_image": []},
            "ignored": {"user_ids": [], "role_ids": [], "channel_ids": []},
        }
        self._invalidate_cache()
        self._save()

    def __repr__(self) -> str:
        return f"<GuildConfig id={self.guild_id} v={self.data.get('_version', 0)} kw={len(self.get_keywords())}>"

    def to_dict(self) -> dict:
        return {
            "settings": self.data.get("settings", {}),
            "keywords": len(self.get_keywords()),
            "actions": {t: len(a) for t, a in self.data.get("actions", {}).items()},
            "ignored": {k: len(v) for k, v in self.data.get("ignored", {}).items()},
            "version": self.data.get("_version", 0),
        }


# ── Guild config registry ──────────────────────────────────────────────

_guild_configs: dict[int, GuildConfig] = {}


def get_guild_config(guild_id: int) -> GuildConfig:
    if guild_id not in _guild_configs:
        _guild_configs[guild_id] = GuildConfig(guild_id)
    return _guild_configs[guild_id]


def remove_guild_config(guild_id: int) -> None:
    _guild_configs.pop(guild_id, None)


def clear_guild_config_cache() -> None:
    _guild_configs.clear()
