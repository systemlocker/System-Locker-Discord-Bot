"""Bridges Discord interaction objects to the pure permission model."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from . import embeds, permissions
from .api import ManagementApi
from .config import GuildConfig, SystemEntry

if TYPE_CHECKING:
    from .bot import SystemLockerBot


def interaction_role_ids(interaction: discord.Interaction) -> frozenset[int]:
    member = interaction.user
    return frozenset(role.id for role in getattr(member, "roles", ()))


def is_guild_administrator(interaction: discord.Interaction) -> bool:
    member = interaction.user
    permissions_ = getattr(member, "guild_permissions", None)
    return bool(permissions_ and permissions_.administrator)


def member_tier(interaction: discord.Interaction, guild: GuildConfig) -> int:
    """The effective permission tier of the invoking user in this guild."""
    return permissions.effective_tier(
        interaction.user.id,
        interaction_role_ids(interaction),
        dict(guild.tier_roles),
        guild.admins,
        guild_administrator=is_guild_administrator(interaction),
    )


def resolve_command_target(
    bot: "SystemLockerBot",
    interaction: discord.Interaction,
    system_name: str | None,
    required_tier: int,
) -> tuple[GuildConfig | None, SystemEntry | None, ManagementApi | None, discord.Embed | None]:
    """Run the shared command preamble.

    Returns ``(guild, entry, api, error)``. When access is denied or the
    system is unknown, ``error`` is an embed the command should send and the
    other fields are ``None``.
    """
    guild = bot.guild_config(interaction)
    if guild is None:
        return None, None, None, embeds.not_configured()
    if member_tier(interaction, guild) < required_tier:
        tier_name = permissions.TIER_NAMES.get(required_tier, "higher")
        return None, None, None, embeds.missing_permission(tier_name)
    if system_name is not None:
        entry = guild.system(system_name)
        if entry is None:
            return None, None, None, embeds.unknown_system(system_name)
        return guild, entry, bot.api_for(entry), None
    return guild, None, None, None
