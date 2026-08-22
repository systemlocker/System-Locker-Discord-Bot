"""Reseller management commands under the /reseller group."""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .. import embeds, format as fmt, guards, permissions
from ..api import (
    ALLOWANCE_DURATION,
    ALLOWANCE_OVERALL,
    RESELLER_NAME_MAX,
    Allowance,
    ResellerPermissions,
)
from ..autocomplete import system_autocomplete
from ..views import confirm

_ALLOWANCE_NONE = "none"

_KEY_LIMIT = app_commands.Range[int, 0, 4_294_967_295]


class ResellersCog(commands.Cog):
    """Commands that manage the resellers of a configured system."""

    def __init__(self, bot) -> None:  # noqa: ANN001 - discord.py passes the bot
        self.bot = bot

    reseller = app_commands.Group(name="reseller", description="Manage resellers")

    # ------------------------------------------------------------------- list

    @reseller.command(name="list", description="List the system's resellers")
    @app_commands.autocomplete(system=system_autocomplete)
    async def reseller_list(self, interaction: discord.Interaction, system: str) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        summaries = await api.list_resellers()
        await interaction.followup.send(
            embed=embeds.reseller_list(system, summaries), ephemeral=True
        )

    # ------------------------------------------------------------------- show

    @reseller.command(name="show", description="Show one reseller's details")
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(token="The reseller token from /reseller list")
    async def reseller_show(
        self, interaction: discord.Interaction, system: str, token: str
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        reseller = await api.get_reseller(token)
        await interaction.followup.send(
            embed=embeds.reseller_details(system, reseller), ephemeral=True
        )

    # ----------------------------------------------------------------- create

    @reseller.command(name="create", description="Create a reseller")
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(
        name=f"Reseller name, up to {RESELLER_NAME_MAX} characters",
        can_create_keys="May generate keys (default yes)",
        can_ban_keys="May permanently delete keys (default no)",
        can_freeze_keys="May freeze and unfreeze keys (default yes)",
        can_reset_hwid="May reset the HWID of keys (default yes)",
        can_access_all_keys="May act on keys it did not create (default no)",
        allowance="Key allowance to configure now (default none)",
        overall_key_limit="Total keys the reseller may generate; required for Overall",
        day_key_limit="Keys per day; required for Duration",
        week_key_limit="Keys per week; required for Duration",
        month_key_limit="Keys per month; required for Duration",
        month_three_key_limit="Keys per three months; required for Duration",
        year_key_limit="Keys per year; required for Duration",
        lifetime_key_limit="Lifetime keys; required for Duration",
    )
    @app_commands.choices(
        allowance=[
            app_commands.Choice(name="No allowance", value=_ALLOWANCE_NONE),
            app_commands.Choice(name="Overall key limit", value=ALLOWANCE_OVERALL),
            app_commands.Choice(name="Duration limits", value=ALLOWANCE_DURATION),
        ]
    )
    async def reseller_create(
        self,
        interaction: discord.Interaction,
        system: str,
        name: str,
        can_create_keys: bool = True,
        can_ban_keys: bool = False,
        can_freeze_keys: bool = True,
        can_reset_hwid: bool = True,
        can_access_all_keys: bool = False,
        allowance: str = _ALLOWANCE_NONE,
        overall_key_limit: Optional[_KEY_LIMIT] = None,
        day_key_limit: Optional[_KEY_LIMIT] = None,
        week_key_limit: Optional[_KEY_LIMIT] = None,
        month_key_limit: Optional[_KEY_LIMIT] = None,
        month_three_key_limit: Optional[_KEY_LIMIT] = None,
        year_key_limit: Optional[_KEY_LIMIT] = None,
        lifetime_key_limit: Optional[_KEY_LIMIT] = None,
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        cleaned = name.strip()
        if not cleaned or len(cleaned) > RESELLER_NAME_MAX:
            return await interaction.response.send_message(
                embed=embeds.error(
                    f"The reseller name must be 1-{RESELLER_NAME_MAX} characters after trimming."
                ),
                ephemeral=True,
            )

        try:
            allowance_object = self._build_allowance(
                allowance,
                overall_key_limit,
                day_key_limit,
                week_key_limit,
                month_key_limit,
                month_three_key_limit,
                year_key_limit,
                lifetime_key_limit,
            )
        except ValueError as value_error:
            return await interaction.response.send_message(
                embed=embeds.error(str(value_error)), ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        reseller = await api.create_reseller(
            cleaned,
            permissions=ResellerPermissions(
                can_create_keys=can_create_keys,
                can_ban_keys=can_ban_keys,
                can_freeze_keys=can_freeze_keys,
                can_reset_hwid=can_reset_hwid,
                can_access_all_keys=can_access_all_keys,
            ),
            allowance=allowance_object,
        )
        # The password is shown once, only to the invoking staff member.
        await interaction.followup.send(
            embed=embeds.reseller_created(system, reseller, password=reseller.password),
            ephemeral=True,
        )
        await self.bot.send_log(interaction, embeds.reseller_created(system, reseller))

    # ------------------------------------------------------------ permissions

    @reseller.command(name="permissions", description="Replace a reseller's permissions")
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(
        token="The reseller token from /reseller list",
        can_create_keys="Leave blank to keep the current setting",
        can_ban_keys="Leave blank to keep the current setting",
        can_freeze_keys="Leave blank to keep the current setting",
        can_reset_hwid="Leave blank to keep the current setting",
        can_access_all_keys="Leave blank to keep the current setting",
    )
    async def reseller_permissions(
        self,
        interaction: discord.Interaction,
        system: str,
        token: str,
        can_create_keys: Optional[bool] = None,
        can_ban_keys: Optional[bool] = None,
        can_freeze_keys: Optional[bool] = None,
        can_reset_hwid: Optional[bool] = None,
        can_access_all_keys: Optional[bool] = None,
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        # The endpoint replaces the whole object, so omitted flags inherit the
        # current values instead of silently dropping to false.
        current = await api.get_reseller_permissions(token)
        overrides = {
            "can_create_keys": can_create_keys,
            "can_ban_keys": can_ban_keys,
            "can_freeze_keys": can_freeze_keys,
            "can_reset_hwid": can_reset_hwid,
            "can_access_all_keys": can_access_all_keys,
        }
        merged = replace(current, **{key: value for key, value in overrides.items() if value is not None})
        result = await api.set_reseller_permissions(token, merged)
        embed = embeds.reseller_permissions(system, token, result)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)

    # -------------------------------------------------------------- allowance

    @reseller.command(name="allowance", description="Replace a reseller's key allowance")
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(
        token="The reseller token from /reseller list",
        overall_key_limit="Total keys the reseller may generate; required for Overall",
        day_key_limit="Keys per day; required for Duration",
        week_key_limit="Keys per week; required for Duration",
        month_key_limit="Keys per month; required for Duration",
        month_three_key_limit="Keys per three months; required for Duration",
        year_key_limit="Keys per year; required for Duration",
        lifetime_key_limit="Lifetime keys; required for Duration",
    )
    @app_commands.choices(
        type=[
            app_commands.Choice(name="Disable the allowance", value=_ALLOWANCE_NONE),
            app_commands.Choice(name="Overall key limit", value=ALLOWANCE_OVERALL),
            app_commands.Choice(name="Duration limits", value=ALLOWANCE_DURATION),
        ]
    )
    async def reseller_allowance(
        self,
        interaction: discord.Interaction,
        system: str,
        token: str,
        type: str,
        overall_key_limit: Optional[_KEY_LIMIT] = None,
        day_key_limit: Optional[_KEY_LIMIT] = None,
        week_key_limit: Optional[_KEY_LIMIT] = None,
        month_key_limit: Optional[_KEY_LIMIT] = None,
        month_three_key_limit: Optional[_KEY_LIMIT] = None,
        year_key_limit: Optional[_KEY_LIMIT] = None,
        lifetime_key_limit: Optional[_KEY_LIMIT] = None,
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        try:
            allowance = self._build_allowance(
                type,
                overall_key_limit,
                day_key_limit,
                week_key_limit,
                month_key_limit,
                month_three_key_limit,
                year_key_limit,
                lifetime_key_limit,
            )
        except ValueError as value_error:
            return await interaction.response.send_message(
                embed=embeds.error(str(value_error)), ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        result = await api.set_reseller_allowance(token, allowance)
        embed = embeds.reseller_allowance(system, token, result)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)

    @reseller.command(name="allowance-remove", description="Remove a reseller's allowance")
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(token="The reseller token from /reseller list")
    async def reseller_allowance_remove(
        self, interaction: discord.Interaction, system: str, token: str
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        await api.remove_reseller_allowance(token)
        embed = embeds.reseller_allowance_removed(system, token)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)

    # ---------------------------------------------------------- reset-password

    @reseller.command(
        name="reset-password", description="Generate a new password for a reseller"
    )
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(token="The reseller token from /reseller list")
    async def reseller_reset_password(
        self, interaction: discord.Interaction, system: str, token: str
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        password = await api.reset_reseller_password(token)
        # The password is shown once, only to the invoking staff member.
        await interaction.followup.send(
            embed=embeds.reseller_password_reset(system, token, password=password),
            ephemeral=True,
        )
        await self.bot.send_log(interaction, embeds.reseller_password_reset(system, token))

    # ----------------------------------------------------------------- delete

    @reseller.command(name="delete", description="Permanently delete a reseller")
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(token="The reseller token from /reseller list")
    async def reseller_delete(
        self, interaction: discord.Interaction, system: str, token: str
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        prompt = embeds.base("🤝 Delete this reseller?", discord.Color.red(), system)
        prompt.description = (
            f"Reseller `{fmt.shorten(token, 64)}` will be **permanently deleted**, together "
            "with its allowance. This cannot be undone."
        )
        if not await confirm(interaction, prompt):
            return
        await api.delete_reseller(token)
        embed = embeds.reseller_deleted(system, token)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)

    # -------------------------------------------------------------- internals

    @staticmethod
    def _build_allowance(
        allowance_type: str,
        overall_key_limit: int | None,
        day_key_limit: int | None,
        week_key_limit: int | None,
        month_key_limit: int | None,
        month_three_key_limit: int | None,
        year_key_limit: int | None,
        lifetime_key_limit: int | None,
    ) -> Allowance:
        duration_limits = {
            "day_key_limit": day_key_limit,
            "week_key_limit": week_key_limit,
            "month_key_limit": month_key_limit,
            "month_three_key_limit": month_three_key_limit,
            "year_key_limit": year_key_limit,
            "lifetime_key_limit": lifetime_key_limit,
        }
        if allowance_type == _ALLOWANCE_NONE:
            if overall_key_limit is not None or any(v is not None for v in duration_limits.values()):
                raise ValueError("Key limits only apply when an allowance type is selected.")
            return Allowance(enabled=False)
        if allowance_type == ALLOWANCE_OVERALL:
            if any(v is not None for v in duration_limits.values()):
                raise ValueError(
                    "day/week/month/3-month/year/lifetime limits only apply to the Duration type."
                )
            if overall_key_limit is None:
                raise ValueError("The Overall type needs overall_key_limit.")
            return Allowance(enabled=True, type=ALLOWANCE_OVERALL, overall_key_limit=overall_key_limit)
        if overall_key_limit is not None:
            raise ValueError("overall_key_limit only applies to the Overall type.")
        missing = [name.replace("_", " ") for name, value in duration_limits.items() if value is None]
        if missing:
            raise ValueError(
                "The Duration type needs all six limits — missing " + ", ".join(missing) + "."
            )
        return Allowance(enabled=True, type=ALLOWANCE_DURATION, **duration_limits)


async def setup(bot) -> None:  # noqa: ANN001 - discord.py extension protocol
    await bot.add_cog(ResellersCog(bot))
