"""Discord bot - ScamGuard. OCR-based crypto scam detection."""

from __future__ import annotations

import argparse
import asyncio
import atexit
import logging
import os
import sys
import warnings
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import colorama
import discord
from discord.ext import commands
from dotenv import load_dotenv

from core.config import config

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


# ── Logging: file + console, our logs only ─────────────────────────
root = logging.getLogger()
for h in root.handlers[:]:
    root.removeHandler(h)

_fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_datefmt = "%Y-%m-%d %H:%M:%S"

console = logging.StreamHandler()
console.setFormatter(ColouredFormatter(_fmt, datefmt=_datefmt))
root.addHandler(console)

log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
file_h = TimedRotatingFileHandler(log_dir / "scanguard.log", when="midnight", backupCount=14, encoding="utf-8")
file_h.setFormatter(logging.Formatter(_fmt, datefmt=_datefmt))
root.addHandler(file_h)

root.setLevel(logging.DEBUG)
# Keep discord/voice libs quiet
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
logging.getLogger("discord.client").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("easyocr").setLevel(logging.WARNING)
logging.getLogger("torch").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

warnings.filterwarnings("ignore", category=UserWarning, module="PIL")
warnings.filterwarnings("ignore", category=UserWarning, module="torch")

log = logging.getLogger("bot")


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


def _cleanup() -> None:
    from core.stats import flush_all
    from cogs._detection import _save_session, _prune_caches
    _prune_caches()
    _save_session()
    flush_all()
    log.info("Stats + session saved on shutdown")


atexit.register(_cleanup)


@bot.event
async def on_guild_remove(guild: discord.Guild) -> None:
    from core.config import remove_guild_config
    remove_guild_config(guild.id)
    log.info("Left guild %s (%d) — config cache cleaned", guild.name, guild.id)


def _apply_logging_level() -> None:
    """Set our loggers level from settings."""
    level_name = config.get("logging_level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    for name in ("bot", "core", "cogs"):
        logging.getLogger(name).setLevel(level)
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
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    log.info("Slash commands synchronised (tree cleared + re-synced)")

    from core.ai_config import ai_config
    ai_config.load()
    log.info("AI config loaded")
    from cogs._detection import _load_session
    _load_session()
    log.info("Session data loaded")

    # Background flush every 30s (safe against SIGKILL)
    async def _periodic_flush():
        while True:
            await asyncio.sleep(30)
            from core.stats import flush_all
            from cogs._detection import _save_session, _prune_caches
            _prune_caches()
            _save_session()
            flush_all()
            log.debug("Background flush done")
    bot._flush_task = asyncio.create_task(_periodic_flush())

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
