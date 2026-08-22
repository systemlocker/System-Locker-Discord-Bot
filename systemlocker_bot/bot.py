"""The bot itself: session lifecycle, API registry, sync, and error handling."""

from __future__ import annotations

import logging
import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from . import embeds, guards
from .api import ApiTransportError, AiohttpTransport, ManagementApi, ManagementApiError
from .config import BotConfig, ConfigError, GuildConfig, SystemEntry, TOKEN_ENV_VARIABLE

log = logging.getLogger("systemlocker_bot.bot")
audit = logging.getLogger("systemlocker_bot.audit")

EXTENSIONS = (
    "systemlocker_bot.cogs.keys",
    "systemlocker_bot.cogs.systems",
    "systemlocker_bot.cogs.variables",
    "systemlocker_bot.cogs.resellers",
    "systemlocker_bot.cogs.security",
    "systemlocker_bot.cogs.meta",
)


class SystemLockerBot(commands.Bot):
    """Slash-command bot speaking the System Locker Management API v2."""

    def __init__(self, config: BotConfig, *, sync_global: bool = False) -> None:
        intents = discord.Intents.default()
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
        )
        self.bot_config = config
        self.sync_global = sync_global
        self._http: aiohttp.ClientSession | None = None
        self._apis: dict[str, ManagementApi] = {}

    # ------------------------------------------------------------- lifecycle

    async def setup_hook(self) -> None:
        self._http = aiohttp.ClientSession(
            headers={"User-Agent": "systemlocker-discord-bot"},
        )
        for extension in EXTENSIONS:
            await self.load_extension(extension)
        self.tree.error(self.on_tree_error)

        # Guild-scoped commands appear instantly in every configured server.
        for guild_id in self.bot_config.guilds:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        if self.sync_global:
            await self.tree.sync()

        systems = sum(len(guild.systems) for guild in self.bot_config.guilds.values())
        log.info(
            "Loaded %d extension(s), %d configured guild(s), %d configured system(s).",
            len(EXTENSIONS), len(self.bot_config.guilds), systems,
        )

    async def close(self) -> None:
        try:
            await super().close()
        finally:
            if self._http is not None and not self._http.closed:
                await self._http.close()

    # ------------------------------------------------------------- accessors

    def guild_config(self, interaction: discord.Interaction) -> GuildConfig | None:
        guild_id = interaction.guild_id
        if guild_id is None:
            return None
        return self.bot_config.guilds.get(guild_id)

    def api_for(self, entry: SystemEntry) -> ManagementApi:
        """One API client per credential, so its rate limit is shared."""
        api = self._apis.get(entry.credential)
        if api is None:
            assert self._http is not None, "setup_hook must run first"
            api = ManagementApi(
                entry.credential,
                entry.system_id,
                transport=AiohttpTransport(self._http),
            )
            self._apis[entry.credential] = api
        return api

    async def send_log(self, interaction: discord.Interaction, embed: discord.Embed) -> None:
        """Mirror a mutation embed to the guild's configured log channel."""
        guild = self.guild_config(interaction)
        if guild is None or guild.log_channel is None:
            return
        channel = self.get_channel(guild.log_channel)
        if channel is None:
            log.warning("Log channel %s not found for guild %s.", guild.log_channel, guild.guild_id)
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.warning("Could not write to log channel %s.", guild.log_channel, exc_info=True)

    # ---------------------------------------------------------- error plumbing

    async def on_tree_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
        audit.warning(
            "ERR command=/%s guild=%s user=%s(%s) error=%s: %s",
            interaction.command and interaction.command.name,
            interaction.guild_id,
            interaction.user,
            interaction.user.id,
            type(original).__name__,
            original,
        )
        if isinstance(original, ManagementApiError):
            embed = embeds.api_error(original)
        elif isinstance(original, ApiTransportError):
            embed = embeds.transport_error()
        else:
            log.exception("Unhandled error in /%s", interaction.command and interaction.command.name)
            embed = embeds.error("An unexpected error occurred. Check the bot's logs.")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            log.warning("Could not deliver an error response.", exc_info=True)

    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: app_commands.Command | app_commands.ContextMenu,
    ) -> None:
        params = " ".join(
            f"{key}={value!r}" for key, value in _namespace_items(interaction)
        )
        audit.info(
            "OK command=/%s guild=%s user=%s(%s) %s",
            command.qualified_name,
            interaction.guild_id,
            interaction.user,
            interaction.user.id,
            params,
        )


def _namespace_items(interaction: discord.Interaction) -> list[tuple[str, object]]:
    namespace = getattr(interaction, "namespace", None)
    try:
        return [(str(key), value) for key, value in namespace]
    except TypeError:
        return []


async def run_bot(config: BotConfig, *, sync_global: bool = False) -> None:
    """Resolve the token and run the bot until disconnected."""
    token = os.environ.get(TOKEN_ENV_VARIABLE) or config.token
    if not token:
        raise ConfigError(
            f"No bot token. Set the {TOKEN_ENV_VARIABLE} environment variable or "
            "the \"token\" field in the configuration file."
        )
    async with SystemLockerBot(config, sync_global=sync_global) as bot:
        await bot.start(token)
