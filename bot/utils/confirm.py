"""View simples de confirmação (Confirmar / Cancelar)."""
from __future__ import annotations

import discord


class Confirm(discord.ui.View):
    def __init__(self, author_id: int, timeout: float = 60,
                 confirm_label: str = "Confirmar", cancel_label: str = "Cancelar"):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: bool | None = None
        self.message: discord.Message | None = None
        self.confirm.label = confirm_label
        self.cancel.label = cancel_label

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Isso não é com você.", ephemeral=True)
            return False
        return True

    @discord.ui.button(style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.value = True
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.value = False
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    async def on_timeout(self) -> None:
        for c in self.children:
            c.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
