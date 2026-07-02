"""Config commands - per-guild configuration via Discord."""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from bot import config as global_cfg
from core.config import get_guild_config, VersionManager, clear_guild_config_cache
from cogs.actions import _build_alert_embed

log = logging.getLogger("bot.config")

TRIGGER_CHOICES = [
    app_commands.Choice(name="scam", value="scam"),
    app_commands.Choice(name="suspicious", value="suspicious"),
    app_commands.Choice(name="banned_image", value="banned_image"),
]
ACTION_CHOICES = [
    app_commands.Choice(name="Supprimer le message", value="delete"),
    app_commands.Choice(name="Avertir en DM", value="warn"),
    app_commands.Choice(name="Exclure (kick)", value="kick"),
    app_commands.Choice(name="Bannir (ban)", value="ban"),
    app_commands.Choice(name="Softban", value="softban"),
    app_commands.Choice(name="Timeout", value="timeout"),
    app_commands.Choice(name="Notifier un salon", value="notify_channel"),
    app_commands.Choice(name="Mentionner un rôle", value="notify_role"),
    app_commands.Choice(name="Mentionner un utilisateur", value="notify_user"),
    app_commands.Choice(name="Ajouter un rôle", value="add_role"),
    app_commands.Choice(name="Retirer un rôle", value="remove_role"),
    app_commands.Choice(name="Journaliser", value="log"),
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


class Config(commands.Cog, name="Config"):
    """Configuration management - per-guild settings, actions, patterns."""

    config = app_commands.Group(name="config", description="Gérer la configuration (par serveur)")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Show ─────────────────────────────────────────────────────────

    @config.command(name="show", description="Afficher la configuration du serveur")
    async def config_show(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        info = gc.to_dict()

        patterns = gc.get_patterns()
        pat_lines = []
        for p in patterns:
            enabled = p.get("enabled", True)
            pat_lines.append(f"{'✅' if enabled else '❌'} `{p['name']}` poids={p['weight']} — {p.get('desc', '')}")
        pat_text = "\n".join(pat_lines) if pat_lines else "Patterns globaux par défaut"

        actions = gc.data.get("actions", {})
        act_lines = []
        for t in ("scam", "suspicious", "banned_image"):
            for i, a in enumerate(actions.get(t, [])):
                extra = ", ".join(f"{k}={v}" for k, v in a.items() if k != "type")
                act_lines.append(f"`[{i}]` **{t}** → `{a['type']}` {extra}")
        act_text = "\n".join(act_lines) if act_lines else "Aucune action configurée"

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

        embed = discord.Embed(
            title=f"Configuration — {interaction.guild.name}",
            colour=discord.Colour.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name=f"Patterns ({len(patterns)})", value=f"```{pat_text[:900]}```", inline=False)
        embed.add_field(name=f"Actions ({sum(len(v) for v in actions.values())})", value=act_text[:1000] or "Aucune", inline=False)
        embed.add_field(name="Paramètres", value=set_text, inline=False)
        embed.set_footer(text=f"v{info['version']} • ID: {interaction.guild_id}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Get / Set ────────────────────────────────────────────────────

    @config.command(name="get", description="Afficher une valeur")
    @app_commands.autocomplete(key=_key_autocomplete)
    async def config_get(self, interaction: discord.Interaction, key: str) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        val = gc.get(key)
        embed = discord.Embed(title=f"Config: {key}", colour=discord.Colour.blue())
        embed.add_field(name="Valeur", value=f"```{val}```", inline=False)
        embed.add_field(name="Type", value=type(val).__name__, inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @config.command(name="set", description="Modifier une valeur")
    @app_commands.autocomplete(key=_key_autocomplete)
    async def config_set(self, interaction: discord.Interaction, key: str, value: str) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        parsed = _parse_value(value)
        try:
            gc.set(key, parsed)
            embed = discord.Embed(title="Config mise à jour", colour=discord.Colour.green())
            embed.add_field(name="Clé", value=f"`{key}`", inline=True)
            embed.add_field(name="Valeur", value=f"```{parsed}```", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Erreur: {exc}", ephemeral=True)

    # ── Actions ──────────────────────────────────────────────────────

    @config.command(name="actions-list", description="Lister les actions")
    @app_commands.choices(trigger=TRIGGER_CHOICES)
    async def config_actions_list(self, interaction: discord.Interaction, trigger: str = None) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        triggers = [trigger] if trigger else ["scam", "suspicious", "banned_image"]
        total = 0
        embed = discord.Embed(title="Actions configurées", colour=discord.Colour.blue())
        for t in triggers:
            actions = gc.get_actions(t)
            total += len(actions)
            if actions:
                lines = [f"`[{i}]` **{a['type']}** " + ", ".join(f"{k}={v}" for k, v in a.items() if k != "type") for i, a in enumerate(actions)]
                embed.add_field(name=f"▸ {t} ({len(actions)})", value="\n".join(lines), inline=False)
            else:
                embed.add_field(name=f"▸ {t}", value="Aucune", inline=False)
        embed.set_footer(text=f"{total} action(s)")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @config.command(name="actions-add", description="Ajouter une action")
    @app_commands.choices(trigger=TRIGGER_CHOICES, action=ACTION_CHOICES)
    @app_commands.describe(
        trigger="Déclencheur",
        action="Type d'action",
        channel="Salon (notify_channel, log)",
        role="Rôle (notify_role, add_role, remove_role)",
        user="Utilisateur (notify_user)",
        duration="Minutes (timeout)",
        message="Texte (warn)",
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
        embed = discord.Embed(title="Action ajoutée", colour=discord.Colour.green())
        embed.add_field(name="Déclencheur", value=trigger, inline=True)
        embed.add_field(name="Action", value=action, inline=True)
        extra = ", ".join(f"{k}={v}" for k, v in entry.items() if k != "type")
        if extra:
            embed.add_field(name="Paramètres", value=extra, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @config.command(name="actions-remove", description="Supprimer une action")
    @app_commands.choices(trigger=TRIGGER_CHOICES)
    async def config_actions_remove(self, interaction: discord.Interaction, trigger: str, index: int) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        ok = gc.remove_action(trigger, index)
        await interaction.followup.send(
            f"Action `[{index}]` supprimée de `{trigger}`." if ok else f"Index invalide.",
            ephemeral=True,
        )

    @config.command(name="actions-clear", description="Vider les actions d'un déclencheur")
    @app_commands.choices(trigger=TRIGGER_CHOICES)
    async def config_actions_clear(self, interaction: discord.Interaction, trigger: str) -> None:
        await interaction.response.defer(ephemeral=True)
        get_guild_config(interaction.guild_id).clear_actions(trigger)
        await interaction.followup.send(f"Actions de `{trigger}` supprimées.", ephemeral=True)

    # ── Patterns ─────────────────────────────────────────────────────

    @config.command(name="patterns-list", description="Lister les patterns")
    async def config_patterns_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        patterns = gc.get_patterns()
        if not patterns:
            await interaction.followup.send("Aucun pattern.", ephemeral=True)
            return
        lines = [f"{'✅' if p.get('enabled', True) else '❌'} `{p['name']}` poids={p['weight']} — {p.get('desc', '')}" for p in patterns]
        pag = "\n".join(lines)
        if len(pag) > 1900:
            pag = pag[:1900] + "\n..."
        embed = discord.Embed(title=f"Patterns ({len(patterns)})", description=pag, colour=discord.Colour.blue())
        await interaction.followup.send(embed=embed, ephemeral=True)

    @config.command(name="patterns-add", description="Ajouter un pattern")
    async def config_patterns_add(self, interaction: discord.Interaction, name: str, pattern: str, weight: int, desc: str = "") -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        ok = gc.add_pattern(name, pattern, weight, desc)
        await interaction.followup.send(f"Pattern `{name}` ajouté." if ok else f"`{name}` existe déjà.", ephemeral=True)

    @config.command(name="patterns-remove", description="Supprimer un pattern")
    async def config_patterns_remove(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        ok = gc.remove_pattern(name)
        await interaction.followup.send(f"Pattern `{name}` supprimé." if ok else f"`{name}` introuvable.", ephemeral=True)

    @config.command(name="patterns-toggle", description="Activer/désactiver un pattern")
    async def config_patterns_toggle(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        state = gc.toggle_pattern(name)
        if state is None:
            await interaction.followup.send(f"`{name}` introuvable.", ephemeral=True)
        else:
            await interaction.followup.send(f"Pattern `{name}` {'activé' if state else 'désactivé'}.", ephemeral=True)

    # ── Ignore ───────────────────────────────────────────────────────

    @config.command(name="ignore", description="Ajouter/retirer un ignoré")
    @app_commands.choices(action=[
        app_commands.Choice(name="Ajouter", value="add"),
        app_commands.Choice(name="Retirer", value="remove"),
    ], target_type=[
        app_commands.Choice(name="Utilisateur", value="user"),
        app_commands.Choice(name="Rôle", value="role"),
        app_commands.Choice(name="Salon", value="channel"),
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
            await interaction.followup.send("Spécifiez un utilisateur, rôle ou salon.", ephemeral=True)
            return
        gc = get_guild_config(interaction.guild_id)
        ok = gc.toggle_ignored(target_type, entity.id, action)
        if ok:
            await interaction.followup.send(f"{entity.mention} {'ajouté' if action == 'add' else 'retiré'} de la liste d'ignorés.", ephemeral=True)
        else:
            await interaction.followup.send(f"{entity.mention} déjà {'dans' if action == 'add' else 'pas dans'} la liste.", ephemeral=True)

    # ── Versions ─────────────────────────────────────────────────────

    @config.command(name="versions-list", description="Lister les versions de config")
    async def config_versions_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        gc = get_guild_config(interaction.guild_id)
        vm = VersionManager(gc)
        versions = vm.list()
        if not versions:
            await interaction.followup.send("Aucun historique de versions.", ephemeral=True)
            return
        lines = [f"`v{v['version']}` — {v['date']}" for v in reversed(versions)]
        embed = discord.Embed(title="Historique des versions", description="\n".join(lines), colour=discord.Colour.blue())
        embed.set_footer(text=f"Version actuelle: v{gc.data.get('_version', 0)}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @config.command(name="versions-revert", description="Revenir à une version précédente")
    async def config_versions_revert(self, interaction: discord.Interaction, version: int) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        gc = get_guild_config(interaction.guild_id)
        vm = VersionManager(gc)
        ok = vm.revert(version)
        if ok:
            await interaction.followup.send(f"✅ Config restaurée à la version `v{version}`.", ephemeral=True)
        else:
            await interaction.followup.send(f"Version `v{version}` introuvable.", ephemeral=True)

    # ── Reload ───────────────────────────────────────────────────────

    @config.command(name="reload", description="Recharger les configs globales depuis les fichiers")
    async def config_reload(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            global_cfg.reload()
            clear_guild_config_cache()
            await interaction.followup.send(
                f"Config rechargée — {len(global_cfg.raw_patterns)} patterns globaux.",
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.followup.send(f"Erreur: {exc}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Config(bot))
