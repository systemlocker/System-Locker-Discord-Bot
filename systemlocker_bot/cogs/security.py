"""Security commands: Aegis IP lookups."""

from __future__ import annotations

import ipaddress

import discord
from discord import app_commands
from discord.ext import commands

from .. import embeds, guards, permissions
from ..autocomplete import system_autocomplete


class SecurityCog(commands.Cog):
    def __init__(self, bot) -> None:  # noqa: ANN001 - discord.py passes the bot
        self.bot = bot

    @app_commands.command(name="iplookup", description="Run an Aegis IP lookup for a system")
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(ip="The IPv4 or IPv6 address to look up")
    async def iplookup(self, interaction: discord.Interaction, system: str, ip: str) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        try:
            ipaddress.ip_address(ip.strip())
        except ValueError:
            return await interaction.response.send_message(
                embed=embeds.error(f"`{ip}` is not a valid IP address."), ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        lookup = await api.ip_lookup(ip.strip())
        await interaction.followup.send(embed=embeds.ip_lookup(system, lookup), ephemeral=True)


async def setup(bot) -> None:  # noqa: ANN001 - discord.py extension protocol
    await bot.add_cog(SecurityCog(bot))
