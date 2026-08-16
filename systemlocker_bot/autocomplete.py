"""Autocomplete callbacks shared by every system-parameterized command."""

from __future__ import annotations

import discord
from discord import app_commands


async def system_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    bot = interaction.client
    guild_config = getattr(bot, "guild_config", None)
    guild = guild_config(interaction) if callable(guild_config) else None
    if guild is None:
        return []
    needle = current.strip().lower()
    matches = [entry.name for entry in guild.systems.values() if needle in entry.name.lower()]
    return [app_commands.Choice(name=name, value=name) for name in matches[:25]]
