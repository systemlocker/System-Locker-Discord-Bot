"""Server-side variable commands under the /variable group."""

from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .. import embeds, guards, permissions
from ..autocomplete import system_autocomplete


class VariablesCog(commands.Cog):
    variable = app_commands.Group(name="variable", description="Manage server-side variables")

    def __init__(self, bot) -> None:  # noqa: ANN001 - discord.py passes the bot
        self.bot = bot

    @variable.command(name="get", description="Read one variable")
    @app_commands.autocomplete(system=system_autocomplete)
    async def variable_get(self, interaction: discord.Interaction, system: str, name: str) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        item = await api.get_variable(name)
        await interaction.followup.send(embed=embeds.variable(system, item), ephemeral=True)

    @variable.command(name="create", description="Create a new variable")
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(
        name="Letters, numbers, underscores; up to 40 characters",
        value="Variable value; up to 500 characters",
        protected="Protected variables are not exposed to unauthenticated clients",
    )
    async def variable_create(
        self,
        interaction: discord.Interaction,
        system: str,
        name: str,
        value: str,
        protected: bool = True,
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        item = await api.create_variable(name.strip(), value, protected=protected)
        embed = embeds.variable(system, item)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)

    @variable.command(name="update", description="Update a variable's value")
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(
        name="The existing variable", value="The new value", protected="Change the protected flag"
    )
    async def variable_update(
        self,
        interaction: discord.Interaction,
        system: str,
        name: str,
        value: str,
        protected: Optional[bool] = None,
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        item = await api.update_variable(name.strip(), value, protected=protected)
        embed = embeds.variable(system, item)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)

    @variable.command(name="delete", description="Delete a variable")
    @app_commands.autocomplete(system=system_autocomplete)
    async def variable_delete(
        self, interaction: discord.Interaction, system: str, name: str
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        await api.delete_variable(name.strip())
        embed = embeds.variable_deleted(system, name.strip())
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)


async def setup(bot) -> None:  # noqa: ANN001 - discord.py extension protocol
    await bot.add_cog(VariablesCog(bot))
