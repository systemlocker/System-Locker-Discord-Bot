"""System-level commands: details, statistics, pause and resume."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from .. import embeds, guards, permissions
from ..autocomplete import system_autocomplete
from ..views import ConfirmView


class SystemsCog(commands.Cog):
    """Commands that read or change system-level state."""

    def __init__(self, bot) -> None:  # noqa: ANN001 - discord.py passes the bot
        self.bot = bot

    @app_commands.command(name="system", description="Show a system's details")
    @app_commands.autocomplete(system=system_autocomplete)
    async def system(self, interaction: discord.Interaction, system: str) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_SUPPORT
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        details = await api.get_system()
        await interaction.followup.send(
            embed=embeds.system_details(system, details), ephemeral=True
        )

    @app_commands.command(name="stats", description="Show online and total user counts")
    @app_commands.autocomplete(system=system_autocomplete)
    async def stats(self, interaction: discord.Interaction, system: str) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_SUPPORT
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        statistics = await api.get_statistics()
        await interaction.followup.send(
            embed=embeds.statistics(system, statistics), ephemeral=True
        )

    @app_commands.command(name="systems", description="List the systems configured for this server")
    async def systems(self, interaction: discord.Interaction) -> None:
        guild, _, _, error = guards.resolve_command_target(
            self.bot, interaction, None, permissions.TIER_SUPPORT
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        lines = [f"{entry.name} — `{entry.system_id}`" for entry in guild.systems.values()]
        embed = embeds.base("🗂️ Configured systems", discord.Color.blue())
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="pause", description="Pause authentication and end active sessions")
    @app_commands.autocomplete(system=system_autocomplete)
    async def pause(self, interaction: discord.Interaction, system: str) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        prompt = embeds.base("⏸️ Pause this system?", discord.Color.orange(), system)
        prompt.description = (
            f"Pausing **{system}** blocks all authentication and ends every active session. "
            "It can be reversed with /resume."
        )
        view = ConfirmView(interaction.user.id)
        message = await interaction.followup.send(embed=prompt, view=view, ephemeral=True)
        timed_out = await view.wait()
        if timed_out or view.result is not True:
            outcome = "Timed out — nothing was changed." if timed_out else "Cancelled — nothing was changed."
            await message.edit(embed=embeds.error(outcome, title="Not confirmed"), view=None)
            return
        await message.edit(view=None)

        result = await api.pause_system()
        embed = embeds.pause_result(system, result, resumed=False, compensate=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)

    @app_commands.command(name="resume", description="Resume authentication for a paused system")
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(
        compensate="Extend key expiries by the paused duration to compensate users"
    )
    async def resume(
        self, interaction: discord.Interaction, system: str, compensate: bool = False
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        result = await api.resume_system(compensate=compensate)
        embed = embeds.pause_result(system, result, resumed=True, compensate=compensate)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)


async def setup(bot) -> None:  # noqa: ANN001 - discord.py extension protocol
    await bot.add_cog(SystemsCog(bot))
