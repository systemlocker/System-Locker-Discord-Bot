"""Interactive components: confirmation prompts for destructive commands."""

from __future__ import annotations

import discord


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
