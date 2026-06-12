"""Paginador que gera uma imagem (grade) por página, com botões de navegação."""
from __future__ import annotations

import discord

from config import settings
from bot.utils.images import render_grid


class ImageGridPaginator(discord.ui.View):
    def __init__(self, ctx, entries: list[tuple[int, bool, str, str]], title: str,
                 footer: str = "", per_page: int = 9, cols: int = 3, timeout: float = 150):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.entries = entries
        self.title = title
        self.footer = footer
        self.per_page = per_page
        self.cols = cols
        self.index = 0
        self.pages = max(1, (len(entries) + per_page - 1) // per_page)
        self.message: discord.Message | None = None
        self._sync()

    def _sync(self) -> None:
        self.first.disabled = self.prev.disabled = self.index == 0
        self.next.disabled = self.last.disabled = self.index >= self.pages - 1
        self.counter.label = f"{self.index + 1}/{self.pages}"

    def _slice(self):
        start = self.index * self.per_page
        return self.entries[start:start + self.per_page]

    async def _build(self):
        buf = await render_grid(self._slice(), cols=self.cols)
        file = discord.File(buf, filename="grade.png")
        emb = discord.Embed(title=self.title, color=settings.color_info)
        emb.set_image(url="attachment://grade.png")
        if self.footer:
            emb.set_footer(text=f"{self.footer} • Página {self.index + 1}/{self.pages}")
        return emb, file

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "Apenas quem usou o comando pode navegar.", ephemeral=True)
            return False
        return True

    async def start(self) -> None:
        emb, file = await self._build()
        view = self if self.pages > 1 else None
        self.message = await self.ctx.send(embed=emb, file=file, view=view)

    async def _show(self, interaction: discord.Interaction) -> None:
        self._sync()
        emb, file = await self._build()
        await interaction.response.edit_message(embed=emb, attachments=[file], view=self)

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
    async def first(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index = 0
        await self._show(interaction)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.primary)
    async def prev(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index = max(0, self.index - 1)
        await self._show(interaction)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.gray, disabled=True)
    async def counter(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        pass

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index = min(self.pages - 1, self.index + 1)
        await self._show(interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def last(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index = self.pages - 1
        await self._show(interaction)

    async def on_timeout(self) -> None:
        for c in self.children:
            c.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
