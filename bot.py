"""Discord bot - ScamGuard. OCR-based crypto scam detection."""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import warnings
from pathlib import Path

import json5

import colorama
import discord
from discord.ext import commands
from dotenv import load_dotenv

colorama.init()

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("FATAL: DISCORD_TOKEN not set in .env", file=sys.stderr)
    sys.exit(1)


class ColouredFormatter(logging.Formatter):
    """Formatter that uses colorama for terminal colours."""

    LEVEL_COLORS = {
        logging.DEBUG: colorama.Fore.CYAN,
        logging.INFO: colorama.Fore.GREEN,
        logging.WARNING: colorama.Fore.YELLOW,
        logging.ERROR: colorama.Fore.RED,
        logging.CRITICAL: colorama.Fore.RED + colorama.Style.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        colour = self.LEVEL_COLORS.get(record.levelno, "")
        reset = colorama.Style.RESET_ALL
        record.levelname = f"{colour}{record.levelname:<8}{reset}"
        return super().format(record)


# Take full control of the root logger (discord.basicConfig adds its own handler)
root = logging.getLogger()
for h in root.handlers[:]:
    root.removeHandler(h)

handler = logging.StreamHandler()
handler.setFormatter(
    ColouredFormatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
)
root.addHandler(handler)
root.setLevel(logging.INFO)

warnings.filterwarnings("ignore", category=UserWarning, module="PIL")
warnings.filterwarnings("ignore", category=UserWarning, module="torch")

log = logging.getLogger("bot")


class ConfigManager:
    """Loads and centralises configuration from the config/ directory."""

    def __init__(self, config_dir: str = "config") -> None:
        self._dir = Path(config_dir)
        self._patterns: list[dict] = []
        self._compiled: list[tuple[str, re.Pattern, int, bool]] = []
        self.settings: dict = {}
        self._loaded = False

    def _load_json5(self, path: Path) -> dict:
        """Load a JSON5 file, returns empty dict if missing."""
        if path.exists():
            with open(path) as f:
                return json5.load(f)
        return {}

    def _save_json(self, path: Path, data: dict) -> None:
        """Write dict as JSON (preserves JSON5 compat for re-reading)."""
        import json
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log.info("Saved %s", path.name)

    def load(self) -> None:
        patterns_path = self._dir / "patterns.json5"
        settings_path = self._dir / "settings.json5"

        data = self._load_json5(patterns_path)
        self._patterns = data.get("patterns", [])
        self._compiled = []
        for p in self._patterns:
            try:
                regex = re.compile(p["pattern"], re.I)
                self._compiled.append(
                    (
                        p["name"],
                        regex,
                        p["weight"],
                        p.get("enabled", True),
                    )
                )
            except re.error as exc:
                log.error("Regex error for '%s': %s", p["name"], exc)

        self.settings = self._load_json5(settings_path)

        self._loaded = True
        log.info(
            "Configuration loaded: %d patterns, %d settings",
            len(self._compiled),
            len(self.settings),
        )

    @property
    def patterns(self) -> list[tuple[str, re.Pattern, int, bool]]:
        if not self._loaded:
            self.load()
        return self._compiled

    @property
    def raw_patterns(self) -> list[dict]:
        if not self._loaded:
            self.load()
        return self._patterns

    def get(self, key: str, default=None):
        if not self._loaded:
            self.load()
        return self.settings.get(key, default)

    def reload(self) -> None:
        self._loaded = False
        self.load()

    def _recompile(self) -> None:
        """Recompile compiled patterns from raw pattern data."""
        self._compiled = []
        for p in self._patterns:
            try:
                regex = re.compile(p["pattern"], re.I)
                self._compiled.append(
                    (p["name"], regex, p["weight"], p.get("enabled", True))
                )
            except re.error as exc:
                log.error("Regex error for '%s': %s", p["name"], exc)

    # ── Setting access ───────────────────────────────────────────────

    def set_setting(self, key: str, value) -> None:
        """Set a runtime setting and persist to disk."""
        if key == "actions":
            return  # actions managed via dedicated commands
        self.settings[key] = value
        self._save_json(self._dir / "settings.json5", self.settings)

    def get_actions(self, trigger: str) -> list:
        """Return action list for a given trigger level."""
        return self.settings.get("actions", {}).get(trigger, [])

    def add_action(self, trigger: str, action: dict) -> None:
        """Add an action to a trigger level and persist."""
        actions = self.settings.setdefault("actions", {})
        actions.setdefault(trigger, []).append(action)
        self._save_json(self._dir / "settings.json5", self.settings)

    def remove_action(self, trigger: str, index: int) -> bool:
        """Remove an action by index. Returns False if invalid."""
        actions = self.settings.get("actions", {}).get(trigger, [])
        if 0 <= index < len(actions):
            actions.pop(index)
            self._save_json(self._dir / "settings.json5", self.settings)
            return True
        return False

    def clear_actions(self, trigger: str) -> None:
        """Clear all actions for a trigger."""
        actions = self.settings.setdefault("actions", {})
        actions[trigger] = []
        self._save_json(self._dir / "settings.json5", self.settings)

    # ── Pattern management ───────────────────────────────────────────

    def add_pattern(
        self, name: str, pattern: str, weight: int, description: str = ""
    ) -> bool:
        """Add a pattern. Returns False if name already exists."""
        for p in self._patterns:
            if p["name"] == name:
                return False
        entry = {
            "name": name,
            "pattern": pattern,
            "weight": weight,
            "enabled": True,
            "desc": description or name,
        }
        self._patterns.append(entry)
        self._recompile()
        self._save_json(self._dir / "patterns.json5", {"patterns": self._patterns})
        return True

    def remove_pattern(self, name: str) -> bool:
        """Remove a pattern by name. Returns False if not found."""
        for i, p in enumerate(self._patterns):
            if p["name"] == name:
                self._patterns.pop(i)
                self._recompile()
                self._save_json(
                    self._dir / "patterns.json5", {"patterns": self._patterns}
                )
                return True
        return False

    def toggle_pattern(self, name: str) -> bool | None:
        """Toggle a pattern's enabled state. Returns new state or None."""
        for p in self._patterns:
            if p["name"] == name:
                p["enabled"] = not p.get("enabled", True)
                self._recompile()
                self._save_json(
                    self._dir / "patterns.json5", {"patterns": self._patterns}
                )
                return p["enabled"]
        return None


config = ConfigManager()


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("!"),
    intents=intents,
    help_command=None,
)


@bot.event
async def on_ready() -> None:
    log.info("Bot connected as %s  (ID: %s)", bot.user, bot.user.id)


@bot.event
async def on_guild_remove(guild: discord.Guild) -> None:
    from core.config import remove_guild_config
    remove_guild_config(guild.id)
    log.info("Left guild %s (%d) — config cache cleaned", guild.name, guild.id)


def _apply_logging_level() -> None:
    """Set root logging level from settings, affecting all loggers."""
    level_name = config.get("logging_level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.getLogger().setLevel(level)
    log.info("Logging level set to %s", level_name)


async def load_cogs() -> None:
    cogs_dir = Path(__file__).parent / "cogs"
    cogs_dir.mkdir(exist_ok=True)
    for f in sorted(cogs_dir.glob("*.py")):
        if f.name.startswith("_"):
            continue
        try:
            await bot.load_extension(f"cogs.{f.stem}")
            log.info("Loaded cog: %s", f.stem)
        except commands.errors.ExtensionFailed as exc:
            log.error("Failed to load %s: %s", f.stem, exc)


@bot.event
async def setup_hook() -> None:
    config.load()
    _apply_logging_level()
    await load_cogs()
    await bot.tree.sync()
    log.info("Slash commands synchronised")

    if not getattr(bot, "light_mode", False):
        monitor = bot.get_cog("Monitor")
        if monitor:
            log.info("Preloading OCR model (use --light to skip) ...")
            await monitor.detector.preload_ocr()
            log.info("OCR model ready")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ScamGuard bot")
    parser.add_argument("--light", action="store_true", help="Skip OCR model preload (faster startup, slower first scan)")
    args = parser.parse_args()
    bot.light_mode = args.light

    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        log.error("Invalid Discord token")
    except Exception as exc:
        log.exception("Unhandled exception: %s", exc)
