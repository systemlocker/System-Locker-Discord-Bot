"""The /help command: an always-current overview of commands and tiers."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from .. import embeds, guards, permissions

_COMMANDS = {
    permissions.TIER_SUPPORT: (
        ("/key system license_key", "Full details for one license key"),
        ("/keylogs system license_key", "Latest authentication log for a key"),
        ("/system system", "System details: version, program hash, pause state"),
        ("/stats system", "Online and total user counts"),
        ("/systems", "List the systems configured for this server"),
        ("/reset system license_key", "Reset the HWID claimed by one key"),
        ("/freeze system license_key", "Freeze a key (blocks authentication)"),
        ("/unfreeze system license_key", "Unfreeze a key"),
    ),
    permissions.TIER_GENERATE: (
        ("/gen system [count] [expiry] …", "Generate 1-100 license keys"),
    ),
    permissions.TIER_MANAGE: (
        ("/addtime system license_key duration", "Add time to a key, e.g. 7d or 12h30m"),
        ("/deletekey system license_key", "Permanently delete a key (asks to confirm)"),
        ("/resetall system", "Reset the HWID of every key (asks to confirm)"),
        ("/pause system", "Pause authentication (asks to confirm)"),
        ("/resume system [compensate]", "Resume a paused system"),
        ("/variable get|create|update|delete", "Manage server-side variables"),
        ("/reseller list|show system", "List resellers or show one reseller"),
        (
            "/reseller create|permissions|allowance|reset-password|delete",
            "Create resellers, manage permissions and allowances",
        ),
        ("/iplookup system ip", "Aegis IP lookup"),
    ),
}


class MetaCog(commands.Cog):
    def __init__(self, bot) -> None:  # noqa: ANN001 - discord.py passes the bot
        self.bot = bot

    @app_commands.command(name="help", description="Show the bot's commands and permission tiers")
    async def help(self, interaction: discord.Interaction) -> None:
        guild = self.bot.guild_config(interaction)
        if guild is None:
            return await interaction.response.send_message(
                embed=embeds.not_configured(), ephemeral=True
            )

        embed = embeds.base("📖 System Locker bot — commands", discord.Color.purple())
        embed.description = (
            "Tiers are cumulative: **generate** includes **support**, and **manage** "
            "includes both. Server administrators and configured admin users always "
            "act at **manage**. Role assignment is configured in the bot's config file."
        )
        for tier in (permissions.TIER_SUPPORT, permissions.TIER_GENERATE, permissions.TIER_MANAGE):
            name = permissions.TIER_NAMES[tier]
            body = "\n".join(f"`{command}` — {description}" for command, description in _COMMANDS[tier])
            embed.add_field(name=f"{name} tier", value=body[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot) -> None:  # noqa: ANN001 - discord.py extension protocol
    await bot.add_cog(MetaCog(bot))
