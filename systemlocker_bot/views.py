"""Interactive components: confirmation prompts for destructive commands."""

from __future__ import annotations

import discord

from . import embeds


class ConfirmView(discord.ui.View):
    """A Confirm/Cancel prompt only the invoking user may answer.

    After ``await view.wait()`` returns, ``view.result`` is ``True`` when
    confirmed, ``False`` when cancelled, and ``None`` when it timed out.
    """

    def __init__(self, author_id: int, *, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.result: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the person who ran this command can answer.", ephemeral=True
            )
            return False
        return True

    async def _finish(self, interaction: discord.Interaction, result: bool) -> None:
        self.result = result
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._finish(interaction, True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._finish(interaction, False)


async def confirm(interaction: discord.Interaction, prompt: discord.Embed) -> bool:
    """Send a confirmation prompt; True only on explicit confirmation.

    The interaction must already be deferred; the prompt is sent as an
    ephemeral followup on behalf of the invoking user.
    """
    view = ConfirmView(interaction.user.id)
    message = await interaction.followup.send(embed=prompt, view=view, ephemeral=True)
    timed_out = await view.wait()
    if timed_out or view.result is not True:
        outcome = "Timed out — nothing was changed." if timed_out else "Cancelled — nothing was changed."
        await message.edit(embed=embeds.error(outcome, title="Not confirmed"), view=None)
        return False
    await message.edit(view=None)
    return True
