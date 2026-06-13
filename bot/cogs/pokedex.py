"""Coleção do jogador: pokédex, listagem, info, seleção e favoritos."""
from __future__ import annotations

import discord
from discord.ext import commands
from sqlalchemy import select

from config import settings
from bot.data.pokemon_data import POKEDEX
from bot.database.db import session_scope
from bot.database.models import PokedexEntry, Pokemon
from bot.utils import embeds, helpers
from bot.utils.confirm import Confirm
from bot.utils.paginator import Paginator, chunk
from bot.utils.rarity import RARITY_EMOJI


def parse_idx_list(text: str, cap: int = 100) -> list[int]:
    """Extrai índices de um texto: '5', '1 2 3', '1-10', '1,2,5-8'."""
    out: set[int] = set()
    for tok in text.replace(",", " ").split():
        if "-" in tok and not tok.startswith("-"):
            a, b = tok.split("-", 1)
            if a.isdigit() and b.isdigit():
                lo, hi = int(a), int(b)
                if 0 < lo <= hi and hi - lo < 1000:
                    out.update(range(lo, hi + 1))
        elif tok.isdigit():
            out.add(int(tok))
    return sorted(out)[:cap]


async def resolve_pokemon(session, user, arg: str | None) -> Pokemon | None:
    """Resolve o pokémon alvo a partir do argumento (idx, 'latest' ou selecionado)."""
    if arg is None or arg.lower() in ("selected", "selecionado"):
        return await helpers.get_selected(session, user)
    if arg.lower() in ("latest", "l", "ultimo", "último"):
        return await session.scalar(
            select(Pokemon).where(Pokemon.owner_id == user.id).order_by(Pokemon.idx.desc())
        )
    if arg.isdigit():
        return await helpers.get_pokemon_by_idx(session, user.id, int(arg))
    return None


class Pokedex(commands.Cog, name="Coleção"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    @commands.command(name="pokemon", aliases=["p", "list", "lista"])
    @commands.guild_only()
    async def pokemon_list(self, ctx: commands.Context, *, filtros: str | None = None) -> None:
        """Lista seus pokémon. Filtros: shiny, fav, legendary, name:<nome>, --iv, --level."""
        flags = (filtros or "").lower().split()
        want_shiny = "shiny" in flags
        want_fav = "fav" in flags or "favorite" in flags
        want_legend = "legendary" in flags or "lendario" in flags
        want_iv = "--iv" in flags or "iv" in flags
        name_filter = next((f.split(":", 1)[1] for f in flags if f.startswith("name:")), None)
        order = Pokemon.idx
        if want_iv:
            order = Pokemon.idx  # ordenaremos depois em memória por IV
        if "--level" in flags or "level" in flags:
            order = Pokemon.level.desc()

        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            mons = await helpers.list_pokemon(session, user.id, order_by=order)
            selected_id = user.selected_id

        # filtragem
        rows = []
        for m in mons:
            sp = POKEDEX.get(m.species_id)
            if sp is None:
                continue
            if want_shiny and not m.shiny:
                continue
            if want_fav and not m.favorite:
                continue
            if want_legend and not sp.legendary:
                continue
            if name_filter and name_filter not in sp.name.lower():
                continue
            rows.append((m, sp))

        if want_iv:
            rows.sort(key=lambda r: r[0].iv_percent, reverse=True)

        if not rows:
            await ctx.send(embed=embeds.err_embed("Nenhum pokémon encontrado com esses filtros."))
            return

        # ---- grade visual estática (sprites cheios, SEM corte) ----
        try:
            from bot.utils.image_paginator import ImageGridPaginator
            if want_iv:
                entries = [
                    (sp.id, m.shiny, sp.name, f"#{m.idx}  IV {m.iv_percent:.0f}%")
                    for m, sp in rows
                ]
            else:
                entries = [
                    (sp.id, m.shiny, sp.name, f"#{m.idx}  Nv{m.level}")
                    for m, sp in rows
                ]
            title = f"📦 Pokémon de {ctx.author.display_name} ({len(rows)})"
            if want_iv:
                title = f"💎 Por IV — {ctx.author.display_name} ({len(rows)})"
            await ImageGridPaginator(
                ctx, entries,
                title=title,
                footer="✨ dourado = shiny • use p!info <#> para detalhes",
                per_page=9, cols=3,
            ).start()
            return
        except Exception:  # noqa: BLE001
            pass

        # ---- fallback: lista de texto ----
        lines = []
        for m, sp in rows:
            marks = ""
            if m.shiny:
                marks += "✨"
            if m.favorite:
                marks += "❤️"
            if m.id == selected_id:
                marks += "📌"
            lines.append(
                f"`#{m.idx:>3}` {RARITY_EMOJI.get(sp.rarity,'')} **{sp.name}** "
                f"• Nv {m.level} • IV {m.iv_percent:.1f}% {marks}"
            )
        pages = [
            discord.Embed(
                title=f"📦 Pokémon de {ctx.author.display_name} ({len(rows)})",
                description="\n".join(group), color=settings.color_info,
            )
            for group in chunk(lines, 15)
        ]
        await Paginator(pages, ctx.author.id).start(ctx)

    # ------------------------------------------------------------------
    @commands.command(name="info", aliases=["i", "show"])
    @commands.guild_only()
    async def info(self, ctx: commands.Context, identificador: str | None = None) -> None:
        """Detalhes de um pokémon. Uso: info <#> | info latest | info (selecionado)."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            poke = await resolve_pokemon(session, user, identificador)
            if poke is None:
                await ctx.send(embed=embeds.err_embed(
                    "Pokémon não encontrado. Use `info <número>`, `info latest` "
                    "ou selecione um com `select <número>`."
                ))
                return
            sp = POKEDEX.get(poke.species_id)
        await ctx.send(embed=embeds.info_embed(sp, poke))

    # ------------------------------------------------------------------
    @commands.command(name="select", aliases=["selecionar"])
    @commands.guild_only()
    async def select_cmd(self, ctx: commands.Context, numero: int) -> None:
        """Define seu LÍDER de time (batalha primeiro e define o nível dos encontros)."""
        from bot.data.gyms import party_slots
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, numero)
            if poke is None:
                await ctx.send(embed=embeds.err_embed(f"Você não tem o pokémon #{numero}."))
                return
            user.selected_id = poke.id
            # vira o LÍDER do time (slot 1): batalha primeiro e define o nível dos encontros
            party = [numero] + [x for x in (user.party or []) if x != numero]
            user.party = party[:party_slots(user.badges)]
            nome = embeds.species_name(sp := POKEDEX.get(poke.species_id), poke.shiny, poke.nickname)
            level, idx = poke.level, poke.idx
        await ctx.send(embed=embeds.ok_embed(
            "Líder do time definido 📌",
            f"**{nome}** (#{idx}, Nv {level}) agora é o **líder** do seu time:\n"
            f"• Ele **batalha primeiro** (você pode trocar no meio com 🔄)\n"
            f"• Define o **nível dos encontros** no `{ctx.prefix}explore`"
        ))

    # ------------------------------------------------------------------
    @commands.command(name="favorite", aliases=["fav", "favoritar"])
    @commands.guild_only()
    async def favorite(self, ctx: commands.Context, numero: int) -> None:
        """Marca um pokémon como favorito (protege contra soltura)."""
        await self._set_favorite(ctx, numero, True)

    @commands.command(name="unfavorite", aliases=["unfav", "desfavoritar"])
    @commands.guild_only()
    async def unfavorite(self, ctx: commands.Context, numero: int) -> None:
        """Remove o status de favorito."""
        await self._set_favorite(ctx, numero, False)

    async def _set_favorite(self, ctx, numero: int, value: bool) -> None:
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, numero)
            if poke is None:
                await ctx.send(embed=embeds.err_embed(f"Você não tem o pokémon #{numero}."))
                return
            poke.favorite = value
            sp = POKEDEX.get(poke.species_id)
        estado = "favoritado ❤️" if value else "desfavoritado 🤍"
        await ctx.send(embed=embeds.ok_embed("Favoritos", f"**{sp.name}** #{numero} {estado}."))

    # ------------------------------------------------------------------
    @commands.command(name="nickname", aliases=["nick", "apelido", "rename"])
    @commands.guild_only()
    async def nickname(self, ctx: commands.Context, numero: int, *, apelido: str | None = None) -> None:
        """Apelida um pokémon (sem texto = remove o apelido)."""
        if apelido and len(apelido) > 32:
            await ctx.send(embed=embeds.err_embed("O apelido deve ter no máximo 32 caracteres."))
            return
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, numero)
            if poke is None:
                await ctx.send(embed=embeds.err_embed(f"Você não tem o pokémon #{numero}."))
                return
            poke.nickname = apelido
        msg = f"Apelido definido para **{apelido}**." if apelido else "Apelido removido."
        await ctx.send(embed=embeds.ok_embed("Apelido", msg))

    # ------------------------------------------------------------------
    @commands.command(name="release", aliases=["soltar", "abandonar", "descartar"])
    @commands.guild_only()
    async def release(self, ctx: commands.Context, *, numeros: str) -> None:
        """Solta pokémon e ganha moedas. Ex.: `release 5` · `release 1 2 3` · `release 1-10`.

        Favoritos são protegidos. Soltar vários pede confirmação.
        """
        idxs = parse_idx_list(numeros)
        if not idxs:
            await ctx.send(embed=embeds.err_embed(
                "Informe os números. Ex.: `release 5`, `release 1 2 3` ou `release 1-10`."))
            return

        # 1) validação
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            found, fav, missing, total = [], [], [], 0
            for idx in idxs:
                poke = await helpers.get_pokemon_by_idx(session, user.id, idx)
                if poke is None:
                    missing.append(idx)
                    continue
                if poke.favorite:
                    fav.append(idx)
                    continue
                sp = POKEDEX.get(poke.species_id)
                reward = 50 + poke.level * 3
                found.append((idx, sp.name, poke.level, reward))
                total += reward

        if not found:
            partes = []
            if fav:
                partes.append("favoritos protegidos: " + ", ".join(f"#{i}" for i in fav))
            if missing:
                partes.append("inexistentes: " + ", ".join(f"#{i}" for i in missing))
            await ctx.send(embed=embeds.err_embed("Nada para soltar. " + (" • ".join(partes))))
            return

        # 2) confirmação se for mais de um
        if len(found) > 1:
            preview = "\n".join(f"• #{i} **{n}** (Nv {lv}) → +{r} 🪙" for i, n, lv, r in found[:15])
            if len(found) > 15:
                preview += f"\n…e mais {len(found) - 15}."
            if fav:
                preview += f"\n🔒 Ignorando {len(fav)} favorito(s)."
            view = Confirm(ctx.author.id, confirm_label=f"Soltar {len(found)} 👋", cancel_label="Cancelar")
            emb = embeds.info_text(
                f"Vai soltar **{len(found)}** pokémon por **{total} 🪙** no total:\n{preview}",
                title="⚠️ Confirmar soltura",
            )
            view.message = await ctx.send(embed=emb, view=view)
            await view.wait()
            if not view.value:
                await ctx.send(embed=embeds.info_text("Soltura cancelada. 🛑"))
                return

        # 3) executar (re-valida e remove do time/seleção)
        released, gained = 0, 0
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            party = list(user.party or [])
            for idx, _name, _lv, reward in found:
                poke = await helpers.get_pokemon_by_idx(session, user.id, idx)
                if poke is None or poke.favorite:
                    continue
                if user.selected_id == poke.id:
                    user.selected_id = None
                if idx in party:
                    party = [p for p in party if p != idx]
                await session.delete(poke)
                gained += reward
                released += 1
            user.party = party
            user.coins += gained

        msg = f"👋 Você soltou **{released}** pokémon e recebeu **{gained} PokéCoins**."
        if fav:
            msg += f"\n🔒 {len(fav)} favorito(s) foram ignorados."
        await ctx.send(embed=embeds.ok_embed("Pokémon solto(s)", msg))

    # ------------------------------------------------------------------
    @commands.command(name="releaseall", aliases=["soltartudo", "abandonartudo"])
    @commands.guild_only()
    async def releaseall(self, ctx: commands.Context) -> None:
        """Solta TODOS os seus pokémon de uma vez. Favoritos ficam protegidos."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            mons = await helpers.list_pokemon(session, user.id)
            to_release = [m for m in mons if not m.favorite]
            fav_count = sum(1 for m in mons if m.favorite)
            total = sum(50 + m.level * 3 for m in to_release)
            count = len(to_release)

        if count == 0:
            await ctx.send(embed=embeds.err_embed(
                "Você não tem pokémon não-favoritos para soltar."))
            return

        view = Confirm(ctx.author.id, confirm_label=f"Soltar {count} 👋", cancel_label="Cancelar")
        emb = embeds.info_text(
            f"Você vai soltar **{count}** pokémon por **{total:,} 🪙** no total.\n"
            f"🔒 **{fav_count}** favorito(s) ficam **protegidos**.\n\n"
            f"⚠️ **Isso é PERMANENTE!** (a Pokédex não é afetada)",
            title="⚠️ Soltar TODOS os pokémon",
        )
        view.message = await ctx.send(embed=emb, view=view)
        await view.wait()
        if not view.value:
            await ctx.send(embed=embeds.info_text("Operação cancelada. 🛑"))
            return

        released, gained = 0, 0
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            mons = await helpers.list_pokemon(session, user.id)
            party = list(user.party or [])
            for m in mons:
                if m.favorite:
                    continue
                if user.selected_id == m.id:
                    user.selected_id = None
                if m.idx in party:
                    party = [p for p in party if p != m.idx]
                gained += 50 + m.level * 3
                await session.delete(m)
                released += 1
            user.party = party
            user.coins += gained

        await ctx.send(embed=embeds.ok_embed(
            "Pokémon soltos 👋",
            f"Você soltou **{released}** pokémon e recebeu **{gained:,} PokéCoins**.\n"
            f"🔒 **{fav_count}** favorito(s) foram mantidos."))

    # ------------------------------------------------------------------
    @commands.command(name="pokedex", aliases=["dex"])
    @commands.guild_only()
    async def pokedex(self, ctx: commands.Context) -> None:
        """Mostra seu progresso de Pokédex (espécies vistas/capturadas)."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            res = await session.scalars(
                select(PokedexEntry).where(PokedexEntry.user_id == user.id)
            )
            entries = {e.species_id: e for e in res}

        total = POKEDEX.count()
        caught = sum(1 for e in entries.values() if e.caught > 0)
        percent = caught / total * 100 if total else 0

        # ---- grade 3x3 estática (capturados coloridos, faltantes em silhueta) ----
        try:
            from bot.utils.image_paginator import ImageGridPaginator
            grid = []
            for sp in POKEDEX.all():
                e = entries.get(sp.id)
                if e and e.caught > 0:
                    grid.append((sp.id, False, sp.name, f"#{sp.id:03d}", False))
                elif e and e.seen > 0:
                    grid.append((sp.id, False, sp.name, f"#{sp.id:03d} • visto", True))
                else:
                    grid.append((sp.id, False, "???", f"#{sp.id:03d}", True))
            await ImageGridPaginator(
                ctx, grid,
                title=f"📕 Pokédex — {caught}/{total} ({percent:.0f}%)",
                footer="colorido = capturado • cinza = falta",
                per_page=9, cols=3,
            ).start()
            return
        except Exception:  # noqa: BLE001
            pass

        # ---- fallback: lista de texto ----
        header = (
            f"**{caught}/{total}** espécies capturadas (**{percent:.1f}%**)\n"
            f"{'🟩' * int(percent // 10)}{'⬜' * (10 - int(percent // 10))}\n​"
        )
        lines = []
        for sp in POKEDEX.all():
            e = entries.get(sp.id)
            mark = "✅" if (e and e.caught > 0) else ("👁️" if (e and e.seen > 0) else "⬜")
            lines.append(f"{mark} `#{sp.id:03d}` {sp.name}")
        pages = [
            discord.Embed(title=f"📕 Pokédex de {ctx.author.display_name}",
                          description=header + "\n".join(group), color=settings.color_default)
            for group in chunk(lines, 20)
        ]
        await Paginator(pages, ctx.author.id).start(ctx)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Pokedex(bot))
