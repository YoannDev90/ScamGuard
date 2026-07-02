"""Discord bot - ScamGuard. OCR-based crypto scam detection."""

from __future__ import annotations

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


if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        log.error("Invalid Discord token")
    except Exception as exc:
        log.exception("Unhandled exception: %s", exc)
