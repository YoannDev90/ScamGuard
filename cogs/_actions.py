"""Action execution engine — runs configured actions on detection triggers."""

from __future__ import annotations

import logging
from typing import Optional

import discord
from core.config import GuildConfig, get_guild_config

log = logging.getLogger("cogs.actions")


def _build_alert_embed(message: discord.Message, result: dict, gc=None, *, trigger: str = "alert", actions_taken: list[str] | None = None) -> discord.Embed:
    """Simple alert embed — message content, actions, user, reports."""
    score = result.get("score", 0)
    if gc is None:
        from core.config import get_guild_config
        gc = get_guild_config(message.guild.id) if message.guild else None
    ec = gc.get("embed_colors", {}) if gc else {}
    scam_colour = ec.get("scam", 0xE74C3C)
    threshold = gc.get("embed_dark_red_threshold", 70) if gc else 70
    colour = discord.Colour.dark_red() if score >= threshold else discord.Colour(scam_colour)

    title = {"scam": "🚨 Scam detected", "suspicious": "⚠️ Suspicious message", "banned_image": "🔞 Banned image detected"}.get(trigger, f"🚨 {trigger}")

    embed = discord.Embed(title=title, colour=colour, timestamp=discord.utils.utcnow())
    embed.add_field(name="Author", value=message.author.mention, inline=True)
    embed.add_field(name="Channel", value=message.channel.mention, inline=True)

    content = message.content
    if content:
        embed.add_field(name="Message", value=f"```{content[:1000]}```", inline=False)

    if actions_taken:
        labels = {"delete": "🗑️ Deleted", "warn": "✉️ DM warning", "kick": "👢 Kicked", "ban": "🔨 Banned", "softban": "🔨 Softbanned", "timeout": "⏰ Timed out", "notify_channel": "📢 Channel notified", "notify_role": "📢 Role pinged", "notify_user": "📢 User notified", "add_role": "➕ Role added", "remove_role": "➖ Role removed", "log": "📋 Logged"}
        desc = "\n".join(f"- {labels.get(a, a)}" for a in actions_taken)
        embed.add_field(name="Actions", value=desc, inline=False)

    factors = result.get("factors", [])
    if factors:
        embed.add_field(name="Reports", value="\n".join(f"- {f}" for f in factors), inline=False)

    embed.set_footer(text=f"ID: {message.id}")
    return embed


_ACTION_PERMS: dict[str, discord.Permissions] = {
    "delete": discord.Permissions(manage_messages=True),
    "kick": discord.Permissions(kick_members=True),
    "ban": discord.Permissions(ban_members=True),
    "softban": discord.Permissions(ban_members=True),
    "timeout": discord.Permissions(moderate_members=True),
    "add_role": discord.Permissions(manage_roles=True),
    "remove_role": discord.Permissions(manage_roles=True),
}


def _has_perm(guild: discord.Guild, atype: str) -> bool:
    need = _ACTION_PERMS.get(atype)
    if need is None:
        return True
    me = guild.me
    if me is None:
        return False
    return me.guild_permissions >= need


async def execute_actions(trigger: str, message: discord.Message, result: dict) -> None:
    """Execute all configured actions for a trigger level (guild-specific)."""
    if not message.guild:
        return
    gc = get_guild_config(message.guild.id)
    actions = gc.get_actions(trigger)
    if not actions:
        log.debug("No actions for trigger='%s' guild=%d", trigger, message.guild.id)
        return

    member = message.author
    guild = message.guild
    reason = result.get("reason", f"ScamGuard: {trigger}")

    action_types = [a.get("type", "?") for a in actions]
    log.info("Executing actions %s for trigger='%s' guild=%d author=%d score=%d", action_types, trigger, guild.id, member.id, result.get("score", 0))

    embed = _build_alert_embed(message, result, gc, trigger=trigger, actions_taken=action_types)

    for action in actions:
        atype = action.get("type")
        if not _has_perm(guild, atype):
            log.warning("Action %s skipped: bot lacks permission guild=%d", atype, guild.id)
            embed.add_field(name="⚠️ Action skipped", value=f"`{atype}` — bot needs `{atype}` permission", inline=False)
            continue
        try:
            if atype == "delete":
                await message.delete()
                log.info("Action: delete msg=%d guild=%d", message.id, guild.id)

            elif atype == "warn":
                default_warn = gc.get("warn_message_default", "Votre message a été signalé.")
                msg = action.get("message", default_warn)
                try:
                    await member.send(f"**{msg}**\nServeur: {guild.name}\nSalon: {message.channel.mention}")
                    log.info("Action: warn DM sent to %d", member.id)
                except discord.Forbidden:
                    log.debug("Action: warn DM blocked for %d", member.id)

            elif atype == "kick":
                await guild.kick(member, reason=reason)
                log.warning("Action: kick %d guild=%d reason=%s", member.id, guild.id, reason)

            elif atype == "ban":
                await guild.ban(member, reason=reason, delete_message_seconds=0)
                log.warning("Action: ban %d guild=%d", member.id, guild.id)

            elif atype == "softban":
                await guild.ban(member, reason=reason, delete_message_seconds=86400)
                await guild.unban(member)
                log.warning("Action: softban %d guild=%d", member.id, guild.id)

            elif atype == "timeout":
                import datetime
                duration = action.get("duration", 60)
                await member.timeout(datetime.timedelta(minutes=duration), reason=reason)
                log.info("Action: timeout %d (%d min) guild=%d", member.id, duration, guild.id)

            elif atype == "notify_channel":
                channel_id = action.get("channel_id")
                target: Optional[discord.TextChannel] = guild.get_channel(channel_id) if channel_id else None
                if target:
                    await target.send(embed=embed)
                    log.info("Action: notify #%s guild=%d", target.name, guild.id)
                else:
                    log.debug("Action: notify_channel channel %s not found guild=%d", channel_id, guild.id)

            elif atype == "notify_role":
                role_id = action.get("role_id")
                role = guild.get_role(role_id) if role_id else None
                ping = role.mention if role else ""
                ch_id = gc.get("alert_channel_id")
                target = guild.get_channel(ch_id) if ch_id else message.channel
                await target.send(content=ping, embed=embed)
                log.info("Action: notify_role %s guild=%d", role.name if role else "?", guild.id)

            elif atype == "notify_user":
                user_ids = action.get("user_ids", [])
                mentions = " ".join(f"<@{uid}>" for uid in user_ids)
                ch_id = gc.get("alert_channel_id")
                target = guild.get_channel(ch_id) if ch_id else message.channel
                await target.send(content=mentions, embed=embed)
                log.info("Action: notify_user %s guild=%d", user_ids, guild.id)

            elif atype == "add_role":
                role_id = action.get("role_id")
                role = guild.get_role(role_id) if role_id else None
                if role:
                    await member.add_roles(role, reason=reason)
                    log.info("Action: +role %s to %d guild=%d", role.name, member.id, guild.id)
                else:
                    log.debug("Action: add_role role %s not found guild=%d", role_id, guild.id)

            elif atype == "remove_role":
                role_id = action.get("role_id")
                role = guild.get_role(role_id) if role_id else None
                if role:
                    await member.remove_roles(role, reason=reason)
                    log.info("Action: -role %s from %d guild=%d", role.name, member.id, guild.id)
                else:
                    log.debug("Action: remove_role role %s not found guild=%d", role_id, guild.id)

            elif atype == "log":
                ch_id = action.get("channel_id") or gc.get("alert_channel_id")
                target = guild.get_channel(ch_id) if ch_id else None
                if target:
                    await target.send(embed=embed)
                    log.info("Action: log to #%s guild=%d", target.name, guild.id)
                else:
                    log.debug("Action: log channel %s not found guild=%d", ch_id, guild.id)

        except discord.Forbidden:
            owner_id = guild.owner_id
            reason = "user is guild owner" if member.id == owner_id else "bot lacks permissions"
            log.warning("Action %s failed for %d guild=%d: %s", atype, member.id, guild.id, reason)
            embed.add_field(name="⚠️ Action failed", value=f"`{atype}` — {reason}", inline=False)
        except discord.HTTPException as exc:
            log.warning("Action %s: HTTP error %d: %s guild=%d", atype, member.id, exc, guild.id)
        except Exception as exc:
            log.error("Action %s failed %d: %s guild=%d", atype, member.id, exc, guild.id)
