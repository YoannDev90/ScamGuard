"""Shared command group — all commands under /config."""

from discord import app_commands

config = app_commands.Group(name="config", description="ScamGuard configuration")
