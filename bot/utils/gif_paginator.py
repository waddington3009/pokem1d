"""Grade 2x2 de GIFs animados, usando o truque de múltiplos embeds com a mesma URL.

Quando vários embeds numa mesma mensagem compartilham o mesmo `url`, o Discord
junta as imagens deles numa grade (até 4). Assim mostramos 4 GIFs animados por página.
"""
from __future__ import annotations

import discord

from config import settings

# URL compartilhada pelos embeds (só precisa ser válida e igual em todos)
_GRID_URL = "https://github.com/waddington3009/pokem1d"


class GifGridPaginator(discord.ui.View):
    def __init__(self, ctx, entries: list[tuple[int, bool, str, str]], title: str,
                 footer: str = "", per_page: int = 4, timeout: float = 150):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.entries = entries
        self.title = title
        self.footer = footer
        self.per_page = per_page
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

    def _build_embeds(self) -> list[discord.Embed]:
        sl = self._slice()
        embeds: list[discord.Embed] = []
        lines: list[str] = []
        for i, (sid, shiny, name, sub) in enumerate(sl):
            e = discord.Embed(
                url=_GRID_URL,
                color=settings.color_shiny if shiny else settings.color_info,
            )
            e.set_image(url=settings.sprite_animated(sid, shiny=shiny))
            embeds.append(e)
            star = "✨" if shiny else ""
            lines.append(f"`{i + 1}.` {star}**{name}** — {sub}")
        # o primeiro embed carrega o texto (título/descrição/rodapé)
        embeds[0].title = self.title
        embeds[0].description = (
            "Posições da grade:  `1` ↖  `2` ↗  `3` ↙  `4` ↘\n\n" + "\n".join(lines)
        )
        foot = f"Página {self.index + 1}/{self.pages}"
        embeds[0].set_footer(text=f"{self.footer} • {foot}" if self.footer else foot)
        return embeds

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "Apenas quem usou o comando pode navegar.", ephemeral=True)
            return False
        return True

    async def start(self) -> None:
        view = self if self.pages > 1 else None
        self.message = await self.ctx.send(embeds=self._build_embeds(), view=view)

    async def _show(self, interaction: discord.Interaction) -> None:
        self._sync()
        await interaction.response.edit_message(embeds=self._build_embeds(), view=self)

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
