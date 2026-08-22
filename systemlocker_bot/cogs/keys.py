"""License-key commands: inspect, generate, freeze, reset, extend, delete."""

from __future__ import annotations

import io

import discord
from discord import app_commands
from discord.ext import commands

from .. import embeds, format as fmt, guards, permissions
from ..api import AfterRedemption, ExpiresAt, Expiry, Perpetual
from ..autocomplete import system_autocomplete
from ..views import confirm

_LIFETIME = "lifetime"
_AFTER_REDEMPTION = "after_redemption"
_AT_DATE = "at"


class KeysCog(commands.Cog):
    """Commands that operate on license keys of a configured system."""

    def __init__(self, bot) -> None:  # noqa: ANN001 - discord.py passes the bot
        self.bot = bot

    # ------------------------------------------------------------------ /key

    @app_commands.command(name="key", description="Show full details for one license key")
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(system="The configured system", license_key="The license key to look up")
    async def key(self, interaction: discord.Interaction, system: str, license_key: str) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_SUPPORT
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        details = await api.get_key(license_key)
        await interaction.followup.send(
            embed=embeds.key_details(system, details), ephemeral=True
        )

    # ------------------------------------------------------------------ /gen

    @app_commands.command(name="gen", description="Generate license keys")
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(
        system="The configured system",
        count="How many keys to create (1-100)",
        expiry="When the generated keys expire",
        duration="Expiry duration, e.g. 7d or 1d12h (expiry = after redemption)",
        expires_at="Fixed expiry date, YYYY-MM-DD [HH:MM] UTC (expiry = at date)",
        notes="Optional note stored with the keys",
        free_trial="Mark the generated keys as free trials",
    )
    @app_commands.choices(
        expiry=[
            app_commands.Choice(name="Lifetime (never expires)", value=_LIFETIME),
            app_commands.Choice(name="Duration after redemption (set duration)", value=_AFTER_REDEMPTION),
            app_commands.Choice(name="Fixed date (set expires_at)", value=_AT_DATE),
        ]
    )
    async def gen(
        self,
        interaction: discord.Interaction,
        system: str,
        count: app_commands.Range[int, 1, 100] = 1,
        expiry: str = _LIFETIME,
        duration: str = "",
        expires_at: str = "",
        notes: str = "",
        free_trial: bool = False,
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_GENERATE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        try:
            expiry_object, expiry_label = self._build_expiry(expiry, duration, expires_at)
        except ValueError as value_error:
            return await interaction.response.send_message(
                embed=embeds.error(str(value_error)), ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        keys = await api.create_keys(
            count,
            expiry=expiry_object,
            notes=notes.strip() or None,
            free_trial=free_trial,
        )

        embed = embeds.keys_generated(
            system,
            keys,
            expiry_label=expiry_label,
            notes=notes,
            free_trial=free_trial,
            requested_by=interaction.user,
        )
        if len(keys) > 10:
            file = discord.File(
                io.BytesIO("\n".join(keys).encode("utf-8")), filename=f"{system}-keys.txt"
            )
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)

    @staticmethod
    def _build_expiry(expiry: str, duration: str, expires_at: str) -> tuple[Expiry, str]:
        if expiry == _LIFETIME:
            if duration or expires_at:
                raise ValueError("duration/expires_at only apply to the other expiry modes.")
            return Perpetual(), "Lifetime"
        if expiry == _AFTER_REDEMPTION:
            if expires_at:
                raise ValueError("expires_at only applies when expiry is 'Fixed date'.")
            seconds = fmt.parse_duration(duration)
            return AfterRedemption(seconds), f"{fmt.format_duration(seconds)} after redemption"
        if expiry == _AT_DATE:
            if duration:
                raise ValueError("duration only applies when expiry is 'Duration after redemption'.")
            when = fmt.parse_input_datetime(expires_at)
            if when <= fmt.utc_now():
                raise ValueError("The fixed expiry date must be in the future.")
            return ExpiresAt(when), fmt.timestamp_line(when)
        raise ValueError("Pick an expiry from the list.")

    # --------------------------------------------------------- /freeze variants

    @app_commands.command(name="freeze", description="Freeze a license key (blocks authentication)")
    @app_commands.autocomplete(system=system_autocomplete)
    async def freeze(self, interaction: discord.Interaction, system: str, license_key: str) -> None:
        await self._set_frozen(interaction, system, license_key, True)

    @app_commands.command(name="unfreeze", description="Unfreeze a license key")
    @app_commands.autocomplete(system=system_autocomplete)
    async def unfreeze(self, interaction: discord.Interaction, system: str, license_key: str) -> None:
        await self._set_frozen(interaction, system, license_key, False)

    async def _set_frozen(
        self, interaction: discord.Interaction, system: str, license_key: str, frozen: bool
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_SUPPORT
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        details = await api.set_frozen(license_key, frozen)
        title = "🧊 Key frozen" if frozen else "🔓 Key unfrozen"
        embed = embeds.key_mutated(title, system, details)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)

    # ----------------------------------------------------------------- /reset

    @app_commands.command(name="reset", description="Reset the HWID claimed by one license key")
    @app_commands.autocomplete(system=system_autocomplete)
    async def reset(self, interaction: discord.Interaction, system: str, license_key: str) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_SUPPORT
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        details = await api.reset_hwid(license_key)
        embed = embeds.key_mutated("🔧 HWID reset", system, details)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)

    # -------------------------------------------------------------- /resetall

    @app_commands.command(name="resetall", description="Reset the HWID of every key in a system")
    @app_commands.autocomplete(system=system_autocomplete)
    async def resetall(self, interaction: discord.Interaction, system: str) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        prompt = embeds.base("♻️ Reset every HWID?", discord.Color.orange(), system)
        prompt.description = (
            f"This clears the claimed hardware ID of **every** key in **{system}**. "
            "Every user will be able to claim their key on a new machine."
        )
        if not await confirm(interaction, prompt):
            return
        updated = await api.reset_all_hwids()
        embed = embeds.hwids_reset(system, updated)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)

    # --------------------------------------------------------------- /addtime

    @app_commands.command(name="addtime", description="Add time to a license key's expiry")
    @app_commands.autocomplete(system=system_autocomplete)
    @app_commands.describe(duration="How much time to add, e.g. 7d or 12h30m")
    async def addtime(
        self, interaction: discord.Interaction, system: str, license_key: str, duration: str
    ) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        try:
            seconds = fmt.parse_duration(duration)
        except ValueError as value_error:
            return await interaction.response.send_message(
                embed=embeds.error(str(value_error)), ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        details = await api.add_time(license_key, seconds)
        embed = embeds.key_mutated(f"⏳ Added {fmt.format_duration(seconds)}", system, details)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)

    # ------------------------------------------------------------ /deletekey

    @app_commands.command(name="deletekey", description="Permanently delete a license key")
    @app_commands.autocomplete(system=system_autocomplete)
    async def deletekey(self, interaction: discord.Interaction, system: str, license_key: str) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_MANAGE
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        prompt = embeds.base("🚫 Delete this key?", discord.Color.red(), system)
        prompt.description = (
            f"`{fmt.shorten(license_key, 64)}` will be **permanently deleted**. "
            "This cannot be undone."
        )
        if not await confirm(interaction, prompt):
            return
        await api.delete_key(license_key)
        embed = embeds.key_deleted(system, license_key)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.send_log(interaction, embed)

    # --------------------------------------------------------------- /keylogs

    @app_commands.command(name="keylogs", description="Show the latest authentication log for a key")
    @app_commands.autocomplete(system=system_autocomplete)
    async def keylogs(self, interaction: discord.Interaction, system: str, license_key: str) -> None:
        _, _, api, error = guards.resolve_command_target(
            self.bot, interaction, system, permissions.TIER_SUPPORT
        )
        if error is not None:
            return await interaction.response.send_message(embed=error, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        entries = await api.key_logs(license_key)
        await interaction.followup.send(
            embed=embeds.key_logs(system, license_key, entries), ephemeral=True
        )


async def setup(bot) -> None:  # noqa: ANN001 - discord.py extension protocol
    await bot.add_cog(KeysCog(bot))
