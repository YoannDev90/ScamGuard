"""Action execution engine — runs configured actions on detection triggers."""

from __future__ import annotations

import logging
from typing import Optional

import discord
from core.config import GuildConfig, get_guild_config

log = logging.getLogger("cogs.actions")


def _build_alert_embed(message: discord.Message, result: dict, gc = None, title: str = None) -> discord.Embed:
    """Standard alert embed builder."""
    score = result.get("score", 0)
    if gc is None:
        from core.config import get_guild_config
        gc = get_guild_config(message.guild.id) if message.guild else None
    ec = gc.get("embed_colors", {}) if gc else {}
    scam_colour = ec.get("scam", 0xE74C3C)
    threshold = gc.get("embed_dark_red_threshold", 70) if gc else 70
    colour = discord.Colour.dark_red() if score >= threshold else discord.Colour(scam_colour)
    embed = discord.Embed(
        title=title or f"Scam alert (score: {score})",
        colour=colour,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Author", value=message.author.mention, inline=True)
    embed.add_field(name="Channel", value=message.channel.mention, inline=True)
    factors = result.get("factors", [])
    if factors:
        embed.add_field(name="Factors", value="\n".join(f"- {f}" for f in factors), inline=False)
    embed.add_field(name="Message", value=f"[Jump]({message.jump_url})", inline=False)
    if result.get("ocr_text"):
        text = result["ocr_text"]
        if len(text) > 1000:
            text = text[:997] + "..."
        embed.add_field(name="OCR text", value=f"```{text}```", inline=False)
    embed.set_footer(text=f"ID: {message.id}")
    return embed


async def execute_actions(trigger: str, message: discord.Message, result: dict) -> None:
    """Execute all configured actions for a trigger level (guild-specific)."""
    if not message.guild:
        return
    gc = get_guild_config(message.guild.id)
    actions = gc.get_actions(trigger)
    if not actions:
        return

    member = message.author
    guild = message.guild
    reason = result.get("reason", f"ScamGuard: {trigger}")

    for action in actions:
        atype = action.get("type")
        try:
            if atype == "delete":
                await message.delete()
                log.info("Action: delete msg %d (guild %d)", message.id, guild.id)

            elif atype == "warn":
                default_warn = gc.get("warn_message_default", "Votre message a été signalé.")
                msg = action.get("message", default_warn)
                try:
                    await member.send(f"**{msg}**\nServeur: {guild.name}\nSalon: {message.channel.mention}")
                    log.info("Action: warn DM to %d", member.id)
                except discord.Forbidden:
                    log.debug("Action: cannot DM %d", member.id)

            elif atype == "kick":
                await guild.kick(member, reason=reason)
                log.warning("Action: kick %d (%s)", member.id, reason)

            elif atype == "ban":
                await guild.ban(member, reason=reason, delete_message_seconds=0)
                log.warning("Action: ban %d (%s)", member.id, reason)

            elif atype == "softban":
                await guild.ban(member, reason=reason, delete_message_seconds=86400)
                await guild.unban(member)
                log.warning("Action: softban %d (%s)", member.id, reason)

            elif atype == "timeout":
                duration = action.get("duration", 60)
                await member.timeout(duration * 60, reason=reason)
                log.info("Action: timeout %d (%d min)", member.id, duration)

            elif atype == "notify_channel":
                channel_id = action.get("channel_id")
                target: Optional[discord.TextChannel] = guild.get_channel(channel_id) if channel_id else None
                if target:
                    embed = _build_alert_embed(message, result, gc, title=f"🔴 Scam alert ({trigger})")
                    await target.send(embed=embed)
                    log.info("Action: notify #%s (guild %d)", target.name, guild.id)

            elif atype == "notify_role":
                role_id = action.get("role_id")
                role = guild.get_role(role_id) if role_id else None
                ping = role.mention if role else ""
                ch_id = gc.get("alert_channel_id")
                target = guild.get_channel(ch_id) if ch_id else message.channel
                embed = _build_alert_embed(message, result, gc, title=f"🔴 Scam alert ({trigger})")
                await target.send(content=ping, embed=embed)

            elif atype == "notify_user":
                user_ids = action.get("user_ids", [])
                mentions = " ".join(f"<@{uid}>" for uid in user_ids)
                ch_id = gc.get("alert_channel_id")
                target = guild.get_channel(ch_id) if ch_id else message.channel
                embed = _build_alert_embed(message, result, gc, title=f"🔴 Scam alert ({trigger})")
                await target.send(content=mentions, embed=embed)

            elif atype == "add_role":
                role_id = action.get("role_id")
                role = guild.get_role(role_id) if role_id else None
                if role:
                    await member.add_roles(role, reason=reason)
                    log.info("Action: +role %s to %d", role.name, member.id)

            elif atype == "remove_role":
                role_id = action.get("role_id")
                role = guild.get_role(role_id) if role_id else None
                if role:
                    await member.remove_roles(role, reason=reason)
                    log.info("Action: -role %s from %d", role.name, member.id)

            elif atype == "log":
                ch_id = action.get("channel_id") or gc.get("alert_channel_id")
                target = guild.get_channel(ch_id) if ch_id else None
                if target:
                    embed = _build_alert_embed(message, result, gc, title=f"📋 Log: {trigger}")
                    await target.send(embed=embed)

        except discord.Forbidden:
            log.warning("Action %s: no perms on %d", atype, member.id)
        except discord.HTTPException as exc:
            log.warning("Action %s: HTTP error %d: %s", atype, member.id, exc)
        except Exception as exc:
            log.error("Action %s failed %d: %s", atype, member.id, exc)
