"""Opt-in public individual-free-trial issuance through Discord."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .. import embeds
from ..api import AfterRedemption, ApiTransportError, ManagementApiError
from ..config import GuildConfig, IndividualFreeTrialConfig

log = logging.getLogger("systemlocker_bot.trials")


class IndividualFreeTrialsCog(commands.Cog):
    """Issue one individual trial per Discord account where a guild opts in."""

    def __init__(self, bot) -> None:  # noqa: ANN001 - discord.py passes the bot
        self.bot = bot
        self._reaction_issues_in_progress: set[tuple[int, int]] = set()

    @app_commands.command(name="trial", description="Get your free trial key by direct message")
    async def trial(self, interaction: discord.Interaction) -> None:
        guild = self.bot.guild_config(interaction)
        settings = guild and guild.individual_free_trial
        if settings is None or not settings.enable:
            return await interaction.response.send_message(
                embed=embeds.error("Free trials are not enabled in this server."), ephemeral=True
            )
        if settings.mode != "command":
            return await interaction.response.send_message(
                embed=embeds.error("This server issues free trials by reaction in its configured channel."),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        delivered, error = await self._issue(interaction.user, guild, settings)
        if delivered:
            await interaction.followup.send("Your free trial key has been sent by DM.", ephemeral=True)
        elif error is not None:
            await interaction.followup.send(embed=error, ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """Issue from a configured channel without needing message-content intent."""
        if payload.guild_id is None:
            return
        guild = self.bot.bot_config.guilds.get(payload.guild_id)
        settings = guild and guild.individual_free_trial
        if (
            settings is None
            or not settings.enable
            or settings.mode != "reaction"
            or payload.channel_id != settings.channel_id
            or str(payload.emoji) != settings.emoji
        ):
            return

        try:
            user = self.bot.get_user(payload.user_id) or await self.bot.fetch_user(payload.user_id)
        except discord.HTTPException:
            log.warning("Could not resolve Discord user %s for a trial reaction.", payload.user_id)
            return
        if user.bot:
            return
        attempt = (payload.guild_id, user.id)
        if attempt in self._reaction_issues_in_progress:
            return
        self._reaction_issues_in_progress.add(attempt)
        try:
            # Re-added reactions should not cause an unsolicited "already used"
            # DM after the member has successfully received their key.
            await self._issue(user, guild, settings, report_existing=False)
        finally:
            self._reaction_issues_in_progress.discard(attempt)

    async def _issue(
        self,
        user: discord.abc.User,
        guild: GuildConfig,
        settings: IndividualFreeTrialConfig,
        *,
        report_existing: bool = True,
    ) -> tuple[bool, discord.Embed | None]:
        """Create a trial and deliver it privately; never place key material in a guild."""
        try:
            # Opening the DM before creating the key catches many privacy failures
            # before an irreversible one-per-identifier trial is consumed.
            dm = user.dm_channel or await user.create_dm()
        except discord.HTTPException:
            return False, embeds.error(
                "I couldn't open a DM with you. Enable direct messages for this server and try again."
            )

        entry = guild.system(settings.system_name)
        assert entry is not None  # Config validation binds this setting to a known system.
        try:
            api = self.bot.api_for(entry)
            identifier = str(user.id)
            if not await api.individual_free_trial_identifier_available(identifier):
                if report_existing:
                    return False, embeds.error("You have already used this system's free trial.")
                return False, None
            key = await api.create_individual_free_trial(
                identifier,
                expiry=AfterRedemption(settings.duration_seconds),
                notes=settings.notes,
            )
        except ManagementApiError as error:
            return False, embeds.api_error(error)
        except ApiTransportError:
            return False, embeds.transport_error()

        try:
            await dm.send(embed=embeds.individual_free_trial(entry.name, key, settings.duration_seconds))
        except discord.HTTPException:
            # A DM channel was opened successfully before creation, so this is an
            # unexpected delivery failure worth preserving for an operator to trace.
            log.error("Created an individual trial for Discord user %s but could not DM it.", user.id)
            return False, embeds.error("Your key was created, but I couldn't deliver the DM. Contact staff.")
        return True, None


async def setup(bot) -> None:  # noqa: ANN001 - discord.py extension protocol
    await bot.add_cog(IndividualFreeTrialsCog(bot))
