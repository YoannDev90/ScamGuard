"""Config commands — per-guild configuration via Discord."""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from bot import config as global_cfg
from core.config import get_guild_config, VersionManager, clear_guild_config_cache

log = logging.getLogger("bot.config")

TRIGGER_CHOICES = [
    app_commands.Choice(name="scam", value="scam"),
    app_commands.Choice(name="suspicious", value="suspicious"),
    app_commands.Choice(name="banned_image", value="banned_image"),
]
ACTION_CHOICES = [
    app_commands.Choice(name="Delete message", value="delete"),
    app_commands.Choice(name="Warn via DM", value="warn"),
    app_commands.Choice(name="Kick", value="kick"),
    app_commands.Choice(name="Ban", value="ban"),
    app_commands.Choice(name="Softban", value="softban"),
    app_commands.Choice(name="Timeout", value="timeout"),
    app_commands.Choice(name="Notify channel", value="notify_channel"),
    app_commands.Choice(name="Ping a role", value="notify_role"),
    app_commands.Choice(name="Notify user", value="notify_user"),
    app_commands.Choice(name="Add role", value="add_role"),
    app_commands.Choice(name="Remove role", value="remove_role"),
    app_commands.Choice(name="Log to channel", value="log"),
]
KNOWN_SETTINGS = [
    "score_alert", "score_warn", "no_text_bonus",
    "message_min_length",
    "image_max_size", "image_download_timeout", "max_ocr_length",
    "language", "banned_images_threshold", "banned_images_score",
    "banned_images_dir",
    "log_channel_names", "alert_channel_id", "ping_role_id",
    "dm_author_on_alert", "dm_message_template", "auto_delete", "cooldown_seconds",
    "community_confirm_count", "report_emoji", "enable_report",
    "reactions", "embed_colors", "embed_dark_red_threshold", "warn_message_default",
    "debug_mode", "logging_level",
]


def _parse_value(value: str):
    if value.lower() in ("true", "yes", "on"):
        return True
    if value.lower() in ("false", "no", "off"):
        return False
    if value.lower() in ("null", "none"):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    try:
        import json as _json
        if value.startswith(("[", "{")):
            return _json.loads(value)
    except Exception:
        pass
    return value


async def _key_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=k, value=k) for k in KNOWN_SETTINGS if current.lower() in k.lower()][:25]


def _ec(gc, key: str, default: int) -> int:
    return gc.get("embed_colors", {}).get(key, default)


class Config(commands.Cog, name="Config"):
    """Configuration management — per-guild settings, actions, patterns."""

    config = app_commands.Group(name="config", description="Manage per-guild configuration")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Show ─────────────────────────────────────────────────────────

    @config.command(name="show", description="Show server configuration")
    async def config_show(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        info = gc.to_dict()

        patterns = gc.get_patterns()
        pat_lines = []
        for p in patterns:
            enabled = p.get("enabled", True)
            pat_lines.append(f"{'✅' if enabled else '❌'} `{p['name']}` weight={p['weight']} — {p.get('desc', '')}")
        pat_text = "\n".join(pat_lines) if pat_lines else "Global defaults"

        actions = gc.data.get("actions", {})
        act_lines = []
        for t in ("scam", "suspicious", "banned_image"):
            for i, a in enumerate(actions.get(t, [])):
                extra = ", ".join(f"{k}={v}" for k, v in a.items() if k != "type")
                act_lines.append(f"`[{i}]` **{t}** → `{a['type']}` {extra}")
        act_text = "\n".join(act_lines) if act_lines else "No actions configured"

        settings_show = {
            "score_alert": gc.get("score_alert", 50),
            "score_warn": gc.get("score_warn", 30),
            "no_text_bonus": gc.get("no_text_bonus", 10),
            "language": "+".join(gc.get("language", ["fr", "en"])),
            "auto_delete": gc.get("auto_delete", False),
            "cooldown_seconds": gc.get("cooldown_seconds", 300),
            "banned_images_threshold": gc.get("banned_images_threshold", 20),
            "banned_images_score": gc.get("banned_images_score", 50),
            "debug_mode": gc.get("debug_mode", False),
            "logging_level": gc.get("logging_level", "INFO"),
        }
        set_text = "\n".join(f"- `{k}` → `{v}`" for k, v in settings_show.items())

        reactions_cfg = gc.get("reactions", {})
        react_text = (
            f"scam: {reactions_cfg.get('scam', '🚨')}\n"
            f"suspicious: {reactions_cfg.get('suspicious', '⚠️')}\n"
            f"banned_img: {reactions_cfg.get('banned_image', '🔞')}\n"
            f"clear: {reactions_cfg.get('clear', '✅')}"
        ) if reactions_cfg else "Defaults"

        ecfg = gc.get("embed_colors", {})
        embed_cfg = gc.get("embed_dark_red_threshold", 70)
        colors_text = (
            f"dark threshold: {embed_cfg}\n"
            f"scam: #{ecfg.get('scam', 0xE74C3C):06x}\n"
            f"suspicious: #{ecfg.get('suspicious', 0xE67E22):06x}\n"
            f"banned_img: #{ecfg.get('banned_image', 0x9B59B6):06x}"
        ) if ecfg else "Defaults"

        embed = discord.Embed(
            title=f"Configuration — {interaction.guild.name}",
            colour=discord.Colour(_ec(gc, "config", 0x3498DB)),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name=f"Patterns ({len(patterns)})", value=f"```{pat_text[:900]}```", inline=False)
        embed.add_field(name=f"Actions ({sum(len(v) for v in actions.values())})", value=act_text[:1000] or "None", inline=False)
        embed.add_field(name="Reactions", value=react_text, inline=True)
        embed.add_field(name="Embed colors", value=colors_text, inline=True)
        embed.add_field(name="Settings", value=set_text, inline=False)
        embed.set_footer(text=f"v{info['version']} • ID: {interaction.guild_id}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Get / Set ────────────────────────────────────────────────────

    @config.command(name="get", description="Show a config value")
    @app_commands.autocomplete(key=_key_autocomplete)
    async def config_get(self, interaction: discord.Interaction, key: str) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        val = gc.get(key)
        embed = discord.Embed(title=f"Config: {key}", colour=discord.Colour(_ec(gc, "config", 0x3498DB)))
        embed.add_field(name="Value", value=f"```{val}```", inline=False)
        embed.add_field(name="Type", value=type(val).__name__, inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @config.command(name="set", description="Update a config value")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.autocomplete(key=_key_autocomplete)
    async def config_set(self, interaction: discord.Interaction, key: str, value: str) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        parsed = _parse_value(value)
        try:
            gc.set(key, parsed)
            embed = discord.Embed(title="Config updated", colour=discord.Colour.green())
            embed.add_field(name="Key", value=f"`{key}`", inline=True)
            embed.add_field(name="Value", value=f"```{parsed}```", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)

    # ── Alert channel (quick-setup) ──────────────────────────────────

    @config.command(name="channel", description="Set the alert/log channel (quick setup)")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(channel="Channel for alerts and logs (default: this channel)")
    async def config_channel(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.followup.send("Select a text channel.", ephemeral=True)
            return
        gc = get_guild_config(interaction.guild_id)
        gc.set("alert_channel_id", target.id)
        embed = discord.Embed(
            title="✅ Alert channel set",
            description=f"Alerts and logs will be sent to {target.mention}",
            colour=discord.Colour.green(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Actions ──────────────────────────────────────────────────────

    @config.command(name="actions-list", description="List configured actions")
    @app_commands.choices(trigger=TRIGGER_CHOICES)
    async def config_actions_list(self, interaction: discord.Interaction, trigger: str = None) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        triggers = [trigger] if trigger else ["scam", "suspicious", "banned_image"]
        total = 0
        embed = discord.Embed(title="Configured actions", colour=discord.Colour(_ec(gc, "config", 0x3498DB)))
        for t in triggers:
            actions = gc.get_actions(t)
            total += len(actions)
            if actions:
                lines = [f"`[{i}]` **{a['type']}** " + ", ".join(f"{k}={v}" for k, v in a.items() if k != "type") for i, a in enumerate(actions)]
                embed.add_field(name=f"▸ {t} ({len(actions)})", value="\n".join(lines), inline=False)
            else:
                embed.add_field(name=f"▸ {t}", value="None", inline=False)
        embed.set_footer(text=f"{total} action(s)")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @config.command(name="actions-add", description="Add an action")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.choices(trigger=TRIGGER_CHOICES, action=ACTION_CHOICES)
    @app_commands.describe(
        trigger="Trigger level",
        action="Action type",
        channel="Channel (notify_channel, log)",
        role="Role (notify_role, add_role, remove_role)",
        user="User (notify_user)",
        duration="Minutes (timeout)",
        message="Custom text (warn)",
    )
    async def config_actions_add(
        self,
        interaction: discord.Interaction,
        trigger: str,
        action: str,
        channel: Optional[discord.TextChannel] = None,
        role: Optional[discord.Role] = None,
        user: Optional[discord.Member] = None,
        duration: Optional[int] = None,
        message: Optional[str] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        entry = {"type": action}
        if channel: entry["channel_id"] = channel.id
        if role: entry["role_id"] = role.id
        if user: entry["user_ids"] = [user.id]
        if duration: entry["duration"] = duration
        if message: entry["message"] = message
        gc.add_action(trigger, entry)
        embed = discord.Embed(title="Action added", colour=discord.Colour.green())
        embed.add_field(name="Trigger", value=trigger, inline=True)
        embed.add_field(name="Action", value=action, inline=True)
        extra = ", ".join(f"{k}={v}" for k, v in entry.items() if k != "type")
        if extra:
            embed.add_field(name="Parameters", value=extra, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @config.command(name="actions-remove", description="Remove an action by index")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.choices(trigger=TRIGGER_CHOICES)
    async def config_actions_remove(self, interaction: discord.Interaction, trigger: str, index: int) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        ok = gc.remove_action(trigger, index)
        await interaction.followup.send(
            f"Action `[{index}]` removed from `{trigger}`." if ok else "Invalid index.",
            ephemeral=True,
        )

    @config.command(name="actions-clear", description="Clear all actions for a trigger")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.choices(trigger=TRIGGER_CHOICES)
    async def config_actions_clear(self, interaction: discord.Interaction, trigger: str) -> None:
        await interaction.response.defer(ephemeral=True)
        get_guild_config(interaction.guild_id).clear_actions(trigger)
        await interaction.followup.send(f"Actions for `{trigger}` cleared.", ephemeral=True)

    # ── Patterns ─────────────────────────────────────────────────────

    @config.command(name="patterns-list", description="List patterns")
    async def config_patterns_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        patterns = gc.get_patterns()
        if not patterns:
            await interaction.followup.send("No patterns.", ephemeral=True)
            return
        lines = [f"{'✅' if p.get('enabled', True) else '❌'} `{p['name']}` weight={p['weight']} — {p.get('desc', '')}" for p in patterns]
        pag = "\n".join(lines)
        if len(pag) > 1900:
            pag = pag[:1900] + "\n..."
        embed = discord.Embed(title=f"Patterns ({len(patterns)})", description=pag, colour=discord.Colour(_ec(gc, "config", 0x3498DB)))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @config.command(name="patterns-add", description="Add a pattern")
    @app_commands.default_permissions(manage_guild=True)
    async def config_patterns_add(self, interaction: discord.Interaction, name: str, pattern: str, weight: int, desc: str = "") -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        ok = gc.add_pattern(name, pattern, weight, desc)
        await interaction.followup.send(f"Pattern `{name}` added." if ok else f"`{name}` already exists.", ephemeral=True)

    @config.command(name="patterns-remove", description="Remove a pattern")
    @app_commands.default_permissions(manage_guild=True)
    async def config_patterns_remove(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        ok = gc.remove_pattern(name)
        await interaction.followup.send(f"Pattern `{name}` removed." if ok else f"`{name}` not found.", ephemeral=True)

    @config.command(name="patterns-toggle", description="Enable/disable a pattern")
    @app_commands.default_permissions(manage_guild=True)
    async def config_patterns_toggle(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        state = gc.toggle_pattern(name)
        if state is None:
            await interaction.followup.send(f"`{name}` not found.", ephemeral=True)
        else:
            await interaction.followup.send(f"Pattern `{name}` {'enabled' if state else 'disabled'}.", ephemeral=True)

    # ── Ignore ───────────────────────────────────────────────────────

    @config.command(name="ignore", description="Add/remove an ignored entity")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
    ], target_type=[
        app_commands.Choice(name="User", value="user"),
        app_commands.Choice(name="Role", value="role"),
        app_commands.Choice(name="Channel", value="channel"),
    ])
    async def config_ignore(
        self,
        interaction: discord.Interaction,
        action: str,
        target_type: str,
        user: Optional[discord.User] = None,
        role: Optional[discord.Role] = None,
        channel: Optional[discord.TextChannel] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        entity = user or role or channel
        if not entity:
            await interaction.followup.send("Specify a user, role or channel.", ephemeral=True)
            return
        gc = get_guild_config(interaction.guild_id)
        ok = gc.toggle_ignored(target_type, entity.id, action)
        if ok:
            await interaction.followup.send(f"{entity.mention} {'added to' if action == 'add' else 'removed from'} ignore list.", ephemeral=True)
        else:
            await interaction.followup.send(f"{entity.mention} already {'in' if action == 'add' else 'not in'} the list.", ephemeral=True)

    # ── Versions ─────────────────────────────────────────────────────

    @config.command(name="versions-list", description="List configuration versions")
    async def config_versions_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        vm = VersionManager(gc)
        versions = vm.list()
        if not versions:
            await interaction.followup.send("No version history.", ephemeral=True)
            return
        lines = [f"`v{v['version']}` — {v['date']}" for v in reversed(versions)]
        embed = discord.Embed(title="Version history", description="\n".join(lines), colour=discord.Colour(_ec(gc, "config", 0x3498DB)))
        embed.set_footer(text=f"Current version: v{gc.data.get('_version', 0)}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @config.command(name="versions-revert", description="Revert to a previous version")
    @app_commands.default_permissions(manage_guild=True)
    async def config_versions_revert(self, interaction: discord.Interaction, version: int) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        gc = get_guild_config(interaction.guild_id)
        vm = VersionManager(gc)
        ok = vm.revert(version)
        if ok:
            await interaction.followup.send(f"Config reverted to version `v{version}`.", ephemeral=True)
        else:
            await interaction.followup.send(f"Version `v{version}` not found.", ephemeral=True)

    # ── Reset ────────────────────────────────────────────────────────

    @config.command(name="reset", description="Reset guild config to defaults")
    @app_commands.default_permissions(manage_guild=True)
    async def config_reset(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        gc.reset()
        await interaction.followup.send("Config reset to defaults.", ephemeral=True)

    # ── Reload ───────────────────────────────────────────────────────

    @config.command(name="reload", description="Reload global config from files")
    @app_commands.default_permissions(manage_guild=True)
    async def config_reload(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            global_cfg.reload()
            clear_guild_config_cache()
            await interaction.followup.send(
                f"Config reloaded — {len(global_cfg.raw_patterns)} global patterns.",
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)


# ── Setup wizard ─────────────────────────────────────────────────────────

PROFILES = {
    "aggressive": {
        "emoji": "🔴", "label": "Aggressive",
        "desc": "Delete + ban + log on scam & banned images. Zero tolerance.",
        "actions": {
            "scam": [{"type": "delete"}, {"type": "ban"}, {"type": "log"}],
            "suspicious": [],
            "banned_image": [{"type": "delete"}, {"type": "ban"}, {"type": "log"}],
        },
    },
    "balanced": {
        "emoji": "🟡", "label": "Balanced",
        "desc": "Delete + timeout + warn + log on scam. Warn + log on suspicious.",
        "actions": {
            "scam": [{"type": "delete"}, {"type": "timeout", "duration": 60}, {"type": "warn"}, {"type": "log"}],
            "suspicious": [{"type": "warn"}, {"type": "log"}],
            "banned_image": [{"type": "delete"}, {"type": "ban"}, {"type": "log"}],
        },
    },
    "gentle": {
        "emoji": "🟢", "label": "Gentle",
        "desc": "Warn + log only. Manual moderation only, no automated bans.",
        "actions": {
            "scam": [{"type": "warn"}, {"type": "log"}],
            "suspicious": [{"type": "warn"}, {"type": "log"}],
            "banned_image": [{"type": "warn"}, {"type": "log"}],
        },
    },
}

class SetupState:
    def __init__(self, guild_id: int, author_id: int):
        self.guild_id = guild_id
        self.author_id = author_id
        self.channel_id: int | None = None
        self.profile: str = "aggressive"
        self.auto_delete: bool = False
        self.dm_author: bool = False
        self.step: int = 0

    def apply(self, gc) -> None:
        gc.set("alert_channel_id", self.channel_id)
        gc.set("auto_delete", self.auto_delete)
        gc.set("dm_author_on_alert", self.dm_author)
        profile = PROFILES[self.profile]
        for trigger, actions in profile["actions"].items():
            gc.clear_actions(trigger)
            for a in actions:
                gc.add_action(trigger, a)

    def summary(self) -> str:
        p = PROFILES[self.profile]
        return (
            f"**Channel:** <#{self.channel_id}>\n"
            f"**Profile:** {p['emoji']} {p['label']}\n"
            f"**Auto-delete:** {'✅' if self.auto_delete else '❌'}\n"
            f"**DM author:** {'✅' if self.dm_author else '❌'}"
        )


_wizards: dict[int, SetupState] = {}


class SetupView(discord.ui.View):
    def __init__(self, state: SetupState, guild: discord.Guild) -> None:
        super().__init__(timeout=300)
        self.state = state
        self.guild = guild

    async def render(self, interaction: discord.Interaction) -> None:
        self.clear_items()
        state = self.state

        if state.step == 0:
            embed = discord.Embed(
                title="🚀 ScamGuard Setup",
                description=(
                    "Let's get your server protected in a few clicks.\n\n"
                    "I'll guide you through:\n"
                    "1. 📢 Pick an alert channel\n"
                    "2. 🛡️ Choose a security profile\n"
                    "3. ⚙️ Extra options\n"
                    "4. ✅ Review & apply\n\n"
                    "You can always tweak everything later with `/config` commands."
                ),
                colour=discord.Colour.blue(),
            )
            embed.set_footer(text="Step 1/4 — Click Next to start")
            self.add_item(NavButton("▶️ Next", "next", self))
            await interaction.response.edit_message(embed=embed, view=self)

        elif state.step == 1:
            embed = discord.Embed(
                title="📢 Alert channel",
                description="Where should I send scam alerts and logs?",
                colour=discord.Colour.blue(),
            )
            embed.set_footer(text="Step 1/4 — Pick a channel or keep current")
            select = ChannelSelect(self.state, self.guild, self)
            self.add_item(select)
            self.add_item(NavButton("◀️ Back", "prev", self))
            self.add_item(NavButton("Next ▶️", "next", self))
            self.add_item(NavButton("⏭️ Skip (current)", "next", self))
            await interaction.response.edit_message(embed=embed, view=self)

        elif state.step == 2:
            embed = discord.Embed(
                title="🛡️ Security profile",
                description="How aggressive should the bot be?\n\n**Aggressive** — Delete + ban + log\n**Balanced** — Delete + timeout + warn + log\n**Gentle** — Warn + log only, no automated bans\n\nYou can customise actions later with `/config actions-add`.",
                colour=discord.Colour.blue(),
            )
            embed.set_footer(text="Step 2/4 — Pick a profile")
            select = ProfileSelect(self.state, self)
            self.add_item(select)
            self.add_item(NavButton("◀️ Back", "prev", self))
            self.add_item(NavButton("Next ▶️", "next", self))
            await interaction.response.edit_message(embed=embed, view=self)

        elif state.step == 3:
            embed = discord.Embed(
                title="⚙️ Extra options",
                description="Toggle additional behaviours:",
                colour=discord.Colour.blue(),
            )
            embed.set_footer(text="Step 3/4 — Toggle options")
            self.add_item(ToggleButton("auto_delete", "🗑️ Auto-delete", "Delete scam messages automatically", self.state, self))
            self.add_item(ToggleButton("dm_author", "✉️ DM author", "Send a DM to the flagged user", self.state, self))
            self.add_item(NavButton("◀️ Back", "prev", self))
            self.add_item(NavButton("Next ▶️", "next", self))
            await interaction.response.edit_message(embed=embed, view=self)

        elif state.step == 4:
            embed = discord.Embed(
                title="✅ Review & apply",
                description=f"{state.summary()}\n\nEverything look good?",
                colour=discord.Colour.green(),
            )
            embed.set_footer(text="Step 4/4 — Confirm to apply")
            self.add_item(NavButton("◀️ Back", "prev", self))
            self.add_item(ConfirmButton(self.state, self.guild, self))

    async def on_timeout(self) -> None:
        gid = self.state.guild_id
        _wizards.pop(gid, None)


class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, state: SetupState, guild: discord.Guild, view: SetupView) -> None:
        super().__init__(channel_types=[discord.ChannelType.text], placeholder="Pick a channel…")
        self._state = state
        self._guild = guild
        self._view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self._state.channel_id = self.values[0].id
        await self._view.render(interaction)


class ProfileSelect(discord.ui.Select):
    def __init__(self, state: SetupState, view: SetupView) -> None:
        self._state = state
        self._view = view
        options = [
            discord.SelectOption(
                label=f"{p['emoji']} {p['label']}",
                description=p["desc"][:100],
                value=key,
                default=key == state.profile,
            )
            for key, p in PROFILES.items()
        ]
        super().__init__(placeholder="Pick a profile…", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        self._state.profile = self.values[0]
        await self._view.render(interaction)


class ToggleButton(discord.ui.Button):
    def __init__(self, attr: str, label: str, desc: str, state: SetupState, view: SetupView) -> None:
        self._attr = attr
        self._state = state
        self._view = view
        current = getattr(state, attr)
        super().__init__(label=f"{'✅' if current else '❌'} {label}", style=discord.ButtonStyle.secondary if not current else discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction) -> None:
        setattr(self._state, self._attr, not getattr(self._state, self._attr))
        await self._view.render(interaction)


class NavButton(discord.ui.Button):
    def __init__(self, label: str, direction: str, view: SetupView) -> None:
        self._direction = direction
        self._view = view
        super().__init__(label=label, style=discord.ButtonStyle.secondary if direction == "prev" else discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self._direction == "next":
            if self._view.state.step == 1 and self._view.state.channel_id is None:
                ch = interaction.channel
                if isinstance(ch, discord.TextChannel):
                    self._view.state.channel_id = ch.id
            self._view.state.step = min(self._view.state.step + 1, 4)
        else:
            self._view.state.step = max(self._view.state.step - 1, 0)
        await self._view.render(interaction)


class ConfirmButton(discord.ui.Button):
    def __init__(self, state: SetupState, guild: discord.Guild, view: SetupView) -> None:
        self._state = state
        self._guild = guild
        self._view = view
        super().__init__(label="✅ Apply configuration", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self._state.channel_id:
            await interaction.response.send_message("Pick an alert channel first.", ephemeral=True)
            return
        gc = get_guild_config(self._state.guild_id)
        self._state.apply(gc)
        _wizards.pop(self._state.guild_id, None)
        embed = discord.Embed(title="✅ Setup complete!", description=self._state.summary(), colour=discord.Colour.green())
        embed.set_footer(text="Use /config to fine-tune")
        await interaction.response.edit_message(embed=embed, view=None)


class ConfigSetup(commands.Cog, name="Setup"):
    """Quick interactive setup wizard."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="setup", description="Interactive setup wizard — configure the bot in a few clicks")
    async def setup(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Use this in a server.", ephemeral=True)
            return
        if _wizards.get(interaction.guild_id):
            await interaction.response.send_message("A setup is already in progress. Finish or wait for timeout.", ephemeral=True)
            return
        state = SetupState(interaction.guild_id, interaction.user.id)
        _wizards[interaction.guild_id] = state
        view = SetupView(state, interaction.guild)
        await view.render(interaction)

    @app_commands.command(name="guide", description="Quick overview: what the bot does and how to use it")
    async def guide(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🛡️ ScamGuard Guide",
            colour=discord.Colour.blue(),
            description=(
                "ScamGuard scans messages for scams using **OCR** (image text recognition) "
                "and **pattern matching** (regex). When a scam is detected, it can automatically "
                "delete, warn, kick, ban, timeout, or log — depending on your config."
            ),
        )
        embed.add_field(
            name="🚀 Quick start",
            value="Run `/setup` — 4 steps, no IDs needed.",
            inline=False,
        )
        embed.add_field(
            name="⚙️ Configuration",
            value=(
                "`/config show` — View current config\n"
                "`/config channel` — Set alert channel\n"
                "`/config set <key> <value>` — Change any setting\n"
                "`/config get <key>` — Read a setting\n"
                "`/config actions-add` — Add an action\n"
                "`/config actions-remove` — Remove an action\n"
                "`/config patterns-list` — View scam patterns\n"
                "`/config reset` — Reset guild config"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔍 Detection",
            value=(
                "**Scam** (score ≥ 50): High-confidence scam — triggers `scam` actions\n"
                "**Suspicious** (score 30-49): Possible scam — triggers `suspicious` actions\n"
                "**Banned image** (phash match): Known scam image — triggers `banned_image` actions"
            ),
            inline=False,
        )
        embed.add_field(
            name="📌 Permissions needed",
            value=(
                "Manage Server users can run `/config` mutations.\n"
                "The bot needs: View Channels, Send Messages, Read History, "
                "Manage Messages, Add Reactions, Kick/Ban/Timeout Members, Manage Roles."
            ),
            inline=False,
        )
        embed.set_footer(text="ScamGuard • Questions? /guide")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Config(bot))
    await bot.add_cog(ConfigSetup(bot))

