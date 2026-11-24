"""Credential scopes and Nightflyer administration."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from .. import embeds, format as fmt, guards, permissions
from ..autocomplete import system_autocomplete
from ..views import confirm

LEASE_PAGE_SIZE = 5


class NightflyerCog(commands.Cog):
    nightflyer = app_commands.Group(name="nightflyer", description="Manage offline authorization leases")

    def __init__(self, bot) -> None:
        self.bot = bot

    @app_commands.command(name="permissions", description="Show the management credential's granted scopes")
    @app_commands.autocomplete(system=system_autocomplete)
    async def credential_permissions(self, interaction: discord.Interaction, system: str) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        scopes = await api.permissions()
        embed = embeds.base("Credential permissions", discord.Color.blue(), system)
        embed.description = "\n".join(f"`{scope}`" for scope in scopes) or "No scopes granted."
        await interaction.followup.send(embed=embed, ephemeral=True)

    @nightflyer.command(name="policy", description="Show the system's offline authorization policy")
    @app_commands.autocomplete(system=system_autocomplete)
    async def policy(self, interaction: discord.Interaction, system: str) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_SUPPORT
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            embed=embeds.nightflyer_policy(system, await api.get_nightflyer_policy()), ephemeral=True
        )

    @nightflyer.command(name="update", description="Change the offline authorization policy")
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(
        enabled="Allow new offline authorizations and renewals",
        max_offline="Maximum offline time in seconds (1200–7776000)",
    )
    async def update(
        self, interaction: discord.Interaction, system: str, enabled: bool | None = None,
        max_offline: app_commands.Range[int, 1200, 7776000] | None = None,
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)
        if enabled is None and max_offline is None:
            return await interaction.response.send_message(
                embed=embeds.error("Provide enabled or max_offline."), ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        prompt = embeds.base("Change Nightflyer policy?", discord.Color.orange(), system)
        prompt.description = (
            f"Change offline authorization for **{system}**?\n\n"
            + embeds.NIGHTFLYER_OFFLINE_NOTICE
        )
        if enabled is not None:
            prompt.add_field(name="Enabled", value="Yes" if enabled else "No")
        if max_offline is not None:
            prompt.add_field(name="Maximum offline seconds", value=str(max_offline))
        if not await confirm(interaction, prompt):
            return
        data = await api.update_nightflyer_policy(enabled=enabled, max_offline=max_offline)
        embed = embeds.nightflyer_policy(system, data)
        embed.title = "Nightflyer policy updated"
        embed.add_field(name="Changed by", value=str(interaction.user), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)

    @nightflyer.command(name="leases", description="List offline leases, optionally filtered by license key")
    @app_commands.autocomplete(system=system_autocomplete)
    async def leases(
        self, interaction: discord.Interaction, system: str, license_key: str | None = None,
        page: app_commands.Range[int, 1, 10000] = 1,
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_SUPPORT
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        leases = await api.nightflyer_leases(license_key, limit=LEASE_PAGE_SIZE, page=page)
        embed = embeds.nightflyer_leases(system, leases, page=page, license_key=license_key)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @nightflyer.command(name="unbind", description="Revoke one offline lease, or all active leases for a key")
    @app_commands.autocomplete(system=system_autocomplete)
    async def unbind(
        self, interaction: discord.Interaction, system: str, license_key: str,
        authorization_id: str | None = None,
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        prompt = embeds.base("Revoke offline authorization?", discord.Color.orange(), system)
        prompt.description = (
            "Revoke the selected lease?" if authorization_id
            else "Revoke every active offline lease for this key?"
        ) + "\n\n" + embeds.NIGHTFLYER_OFFLINE_NOTICE
        prompt.add_field(name="License key", value=fmt.shorten(license_key, 128), inline=False)
        prompt.add_field(
            name="Authorization", value=fmt.shorten(authorization_id, 128) or "All active leases",
            inline=False,
        )
        if not await confirm(interaction, prompt):
            return
        if authorization_id:
            data = await api.unbind_nightflyer_lease(license_key, authorization_id)
            message = "Lease revoked." if data.get("transitioned") else "Lease was already inactive."
        else:
            count = await api.unbind_all_nightflyer_leases(license_key)
            message = f"Revoked {count} active lease(s)."
        embed = embeds.base("Nightflyer unbinding", discord.Color.green(), system)
        embed.description = message + "\n\n" + embeds.NIGHTFLYER_OFFLINE_NOTICE
        embed.add_field(name="License key", value=fmt.shorten(license_key, 128), inline=False)
        embed.add_field(
            name="Authorization", value=fmt.shorten(authorization_id, 128) or "All active leases",
            inline=False,
        )
        embed.add_field(name="Changed by", value=str(interaction.user), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)


async def setup(bot) -> None:
    await bot.add_cog(NightflyerCog(bot))
