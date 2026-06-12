"""Sistema de Liga: 8 ginásios + Elite dos 4 + Campeão (tudo PvE)."""
from __future__ import annotations

import time

import discord
from discord.ext import commands

from config import settings
from bot.data.gyms import (
    CHALLENGES,
    CHALLENGES_BY_KEY,
    challenge_index,
    party_slots,
    resolve_challenge,
)
from bot.data.items import get_item
from bot.data.pokemon_data import POKEDEX
from bot.data.types import TYPE_EMOJI
from bot.database.db import session_scope
from bot.utils import embeds, helpers

REMATCH_CD = 6 * 3600  # 6h entre revanches do mesmo desafio


class Gyms(commands.Cog, name="Liga"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    @commands.command(name="gyms", aliases=["ginasios", "ginásios", "liga", "league"])
    @commands.guild_only()
    async def gyms(self, ctx: commands.Context) -> None:
        """Lista os desafios da Liga e o seu progresso."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            badges = set(user.badges or [])
            slots = party_slots(user.badges)

        lines = []
        for i, c in enumerate(CHALLENGES):
            if c.key in badges:
                st = "✅"
            elif i == 0 or CHALLENGES[i - 1].key in badges:
                st = "▶️"
            else:
                st = "🔒"
            lvl = max(l for _, l in c.team)
            tag = "👑 " if c.kind == "champion" else ("⭐ " if c.kind == "elite" else "")
            lines.append(f"{st} `{i + 1:>2}` {c.emoji} {tag}**{c.name}** — {c.leader} (Nv~{lvl})")

        emb = discord.Embed(
            title="🏆 Liga Pokémon",
            description="\n".join(lines),
            color=settings.color_default,
        )
        emb.add_field(name="Insígnias", value=f"🎖️ {len(badges)}/{len(CHALLENGES)}", inline=True)
        emb.add_field(name="Time atual", value=f"{slots} slots", inline=True)
        emb.set_footer(text=f"Desafie com {ctx.prefix}gym <número/nome>  •  ▶️ disponível  🔒 trancado")
        await ctx.send(embed=emb)

    # ------------------------------------------------------------------
    @commands.command(name="badges", aliases=["insignias", "insígnias", "medals"])
    @commands.guild_only()
    async def badges(self, ctx: commands.Context, membro: discord.Member | None = None) -> None:
        """Mostra as insígnias conquistadas."""
        alvo = membro or ctx.author
        async with session_scope() as session:
            user = await helpers.fetch_user(session, alvo.id)
            blist = list(user.badges or [])

        earned = [CHALLENGES_BY_KEY[k] for k in blist if k in CHALLENGES_BY_KEY]
        champ = "champion" in blist
        title = f"🎖️ Insígnias de {alvo.display_name} ({len(earned)}/{len(CHALLENGES)})"
        if champ:
            title = "👑 CAMPEÃO " + title
        if not earned:
            desc = "Nenhuma insígnia ainda. Comece pelo `p!gym 1`!"
        else:
            desc = "  ".join(c.emoji for c in earned) + "\n\n" + "\n".join(
                f"{c.emoji} **{c.badge}** — {c.name}" for c in earned)
        await ctx.send(embed=discord.Embed(title=title, description=desc, color=settings.color_default))

    # ------------------------------------------------------------------
    @commands.command(name="gym", aliases=["ginasio", "ginásio", "desafiar", "elite", "champion", "campeao"])
    @commands.guild_only()
    async def gym(self, ctx: commands.Context, *, alvo: str | None = None) -> None:
        """Desafia um líder. Uso: gym <número 1-13 | nome>. Ex.: `gym 1` ou `gym fogo`."""
        # aliases diretos pulam para o desafio certo
        if alvo is None:
            inv = ctx.invoked_with.lower()
            if inv in ("elite",):
                alvo = "elite1"
            elif inv in ("champion", "campeao"):
                alvo = "champion"
        if alvo is None:
            await ctx.send(embed=embeds.err_embed(
                f"Diga qual desafio. Ex.: `{ctx.prefix}gym 1` ou `{ctx.prefix}gym fogo`. "
                f"Veja a lista em `{ctx.prefix}gyms`."))
            return

        ch = resolve_challenge(alvo)
        if ch is None:
            await ctx.send(embed=embeds.err_embed(f"Desafio **{alvo}** não encontrado. Veja `{ctx.prefix}gyms`."))
            return
        idx = challenge_index(ch.key)

        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            badges = list(user.badges or [])

        # trancado? precisa vencer o anterior
        if idx > 0 and CHALLENGES[idx - 1].key not in badges:
            prev = CHALLENGES[idx - 1]
            await ctx.send(embed=embeds.err_embed(
                f"🔒 Trancado! Vença antes: **{prev.name}** ({prev.leader}). Use `{ctx.prefix}gyms`."))
            return

        # carrega o time do jogador
        battle_cog = self.bot.get_cog("Batalha")
        if battle_cog is None:
            await ctx.send(embed=embeds.err_embed("Sistema de batalha indisponível."))
            return
        p1_team, err = await battle_cog.load_team(ctx, ctx.author)
        if not p1_team:
            await ctx.send(embed=embeds.err_embed(err))
            return

        # monta o time do líder (PvE — IA)
        from bot.cogs.battle import build_wild_mon
        leader_team = [build_wild_mon(POKEDEX.by_name(n), lv, name=n) for n, lv in ch.team]

        # intro
        time_txt = " ".join(f"{POKEDEX.by_name(n).name} Nv{lv}" for n, lv in ch.team)
        intro = discord.Embed(
            title=f"{ch.emoji} {ch.name}",
            description=(f"**{ch.leader}** aceitou seu desafio!\n"
                        f"Time do líder: {time_txt}\n\n"
                        f"{'⚠️ ' if ch.kind != 'gym' else ''}Boa sorte, treinador!"),
            color=settings.color_default,
        )
        await ctx.send(embed=intro)

        pid = ctx.author.id
        already = ch.key in badges

        async def on_finish(winner, loser):
            await self._resolve(ctx, ch, pid, winner.owner_id == pid, already)

        await battle_cog.launch_battle(
            ctx, p1_team, leader_team, pid, None,
            on_finish=on_finish, opponent_name=ch.leader)

    # ------------------------------------------------------------------
    async def _resolve(self, ctx, ch, pid: int, won: bool, already: bool) -> None:
        if not won:
            await ctx.send(embed=embeds.err_embed(
                f"Você foi derrotado por **{ch.leader}**... treine seu time e volte! 💪",
                title="Derrota"))
            return

        extra = ""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, pid)
            badges = list(user.badges or [])
            if ch.key not in badges:
                # primeira vitória: insígnia + moedas + item
                before_slots = party_slots(badges)
                badges.append(ch.key)
                user.badges = badges
                user.badge_count = len(badges)
                user.coins += ch.reward_coins
                lines = [f"🎖️ Você ganhou a **{ch.badge}** {ch.emoji}!",
                         f"💰 +{ch.reward_coins:,} PokéCoins"]
                it = get_item(ch.reward_item) if ch.reward_item else None
                if it is not None:
                    await helpers.add_item(session, user.id, it.key, ch.reward_item_qty)
                    lines.append(f"{it.emoji} +{ch.reward_item_qty}× {it.name}")
                after_slots = party_slots(badges)
                if after_slots > before_slots:
                    lines.append(f"📈 Seu time aumentou para **{after_slots} slots**!")
                if ch.kind == "champion":
                    lines.append("👑 **VOCÊ É O CAMPEÃO DA LIGA!** Lenda absoluta! 🏆")
                title = ("👑 CAMPEÃO!" if ch.kind == "champion" else "🏆 Vitória no desafio!")
                extra = "\n".join(lines)
            else:
                # revanche: moedas com cooldown
                title = "🔁 Revanche vencida!"
                cds = dict(user.gym_cooldowns or {})
                now = time.time()
                last = cds.get(ch.key, 0)
                if now - last >= REMATCH_CD:
                    reward = max(1, ch.reward_coins // 4)
                    user.coins += reward
                    cds[ch.key] = now
                    user.gym_cooldowns = cds
                    extra = f"💰 +{reward:,} PokéCoins (revanche)."
                else:
                    h = int((REMATCH_CD - (now - last)) // 3600)
                    m = int(((REMATCH_CD - (now - last)) % 3600) // 60)
                    extra = f"Você já bateu este líder hoje. Próxima recompensa de revanche em **{h}h {m}min**."

        await ctx.send(embed=embeds.ok_embed(title, extra))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Gyms(bot))
