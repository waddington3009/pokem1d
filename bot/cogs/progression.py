"""Progressão social: perfil, ranking, missões diárias e conquistas."""
from __future__ import annotations

import discord
from discord.ext import commands
from sqlalchemy import func, select

from config import settings
from bot.data.pokemon_data import POKEDEX
from bot.database.db import session_scope
from bot.database.models import PokedexEntry, User
from bot.utils import embeds, helpers
from bot.utils.progression import (
    ACHIEVEMENTS,
    claim_quest,
    quest_state,
)

LEADERBOARD_TYPES = {
    "caught": ("total_caught", "🎯 Mais Capturas", "capturas"),
    "shiny": ("total_shiny", "✨ Mais Shinies", "shinies"),
    "coins": ("coins", "💰 Mais Ricos", "PokéCoins"),
    "battles": ("battles_won", "⚔️ Mais Vitórias", "vitórias"),
    "level": ("trainer_level", "🎖️ Maiores Níveis", "nível"),
}


class Progression(commands.Cog, name="Progressão"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    @commands.command(name="profile", aliases=["perfil", "trainer"])
    @commands.guild_only()
    async def profile(self, ctx: commands.Context, membro: discord.Member | None = None) -> None:
        """Mostra o perfil de treinador."""
        alvo = membro or ctx.author
        async with session_scope() as session:
            user = await helpers.fetch_user(session, alvo.id)
            total_pokes = await helpers.pokemon_count(session, user.id)
            dex_caught = await session.scalar(
                select(func.count(PokedexEntry.id)).where(
                    PokedexEntry.user_id == user.id, PokedexEntry.caught > 0
                )
            ) or 0
            selected = await helpers.get_selected(session, user)
            sel_txt = "—"
            if selected:
                sp = POKEDEX.get(selected.species_id)
                sel_txt = f"{embeds.species_name(sp, selected.shiny, selected.nickname)} (Nv {selected.level})"
            stats = {
                "level": user.trainer_level, "xp": user.trainer_xp, "xp_next": user.xp_to_next,
                "coins": user.coins, "caught": user.total_caught, "shiny": user.total_shiny,
                "bw": user.battles_won, "bt": user.battles_total, "ach": len(user.achievements or []),
                "streak": user.daily_streak,
            }

        total_dex = POKEDEX.count()
        winrate = (stats["bw"] / stats["bt"] * 100) if stats["bt"] else 0

        emb = discord.Embed(title=f"🎖️ Treinador {alvo.display_name}", color=settings.color_default)
        emb.set_thumbnail(url=alvo.display_avatar.url)
        emb.add_field(name="Nível", value=f"{stats['level']} ({stats['xp']}/{stats['xp_next']} XP)", inline=True)
        emb.add_field(name="PokéCoins", value=f"{stats['coins']:,}", inline=True)
        emb.add_field(name="Streak diário", value=f"🔥 {stats['streak']}", inline=True)
        emb.add_field(name="Capturas totais", value=f"{stats['caught']:,}", inline=True)
        emb.add_field(name="Shinies", value=f"✨ {stats['shiny']}", inline=True)
        emb.add_field(name="Pokémon na coleção", value=f"{total_pokes}", inline=True)
        emb.add_field(name="Pokédex", value=f"{dex_caught}/{total_dex}", inline=True)
        emb.add_field(name="Batalhas", value=f"{stats['bw']}V / {stats['bt']}  ({winrate:.0f}%)", inline=True)
        emb.add_field(name="Conquistas", value=f"🏅 {stats['ach']}/{len(ACHIEVEMENTS)}", inline=True)
        emb.add_field(name="Selecionado", value=sel_txt, inline=False)
        await ctx.send(embed=emb)

    # ------------------------------------------------------------------
    @commands.command(name="leaderboard", aliases=["top", "ranking", "lb"])
    @commands.guild_only()
    async def leaderboard(self, ctx: commands.Context, tipo: str = "caught") -> None:
        """Ranking de jogadores. Tipos: caught, shiny, coins, battles, level."""
        tipo = tipo.lower()
        _aliases = {
            "vitorias": "battles", "vitórias": "battles", "wins": "battles",
            "win": "battles", "duelos": "battles", "duels": "battles", "duel": "battles",
            "moedas": "coins", "dinheiro": "coins", "money": "coins",
            "capturas": "caught", "catches": "caught", "captured": "caught",
            "nivel": "level", "nível": "level", "levels": "level", "lv": "level",
            "shinies": "shiny",
        }
        tipo = _aliases.get(tipo, tipo)
        if tipo not in LEADERBOARD_TYPES:
            await ctx.send(embed=embeds.err_embed(
                f"Tipos válidos: {', '.join(LEADERBOARD_TYPES)}."
            ))
            return
        column_name, title, unit = LEADERBOARD_TYPES[tipo]
        column = getattr(User, column_name)

        async with session_scope() as session:
            res = await session.scalars(
                select(User).order_by(column.desc()).limit(10)
            )
            users = list(res)

        medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
        lines = []
        for i, u in enumerate(users):
            value = getattr(u, column_name)
            if value == 0 and tipo != "level":
                continue
            lines.append(f"{medals[i]} <@{u.discord_id}> — **{value:,}** {unit}")

        emb = discord.Embed(
            title=f"{title}",
            description="\n".join(lines) or "Ninguém no ranking ainda.",
            color=settings.color_info,
        )
        emb.set_footer(text=f"Use {ctx.prefix}top <caught|shiny|coins|battles|level>")
        await ctx.send(embed=emb)

    # ------------------------------------------------------------------
    @commands.command(name="quests", aliases=["missions", "missoes", "missões", "daily-quests"])
    @commands.guild_only()
    async def quests(self, ctx: commands.Context) -> None:
        """Mostra as missões diárias e coleta as recompensas concluídas."""
        claimed_now = []
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            # coleta automática das missões concluídas
            for q, current, done, was_claimed in quest_state(user):
                if done and not was_claimed:
                    claimed = claim_quest(user, q.key)
                    if claimed:
                        user.coins += claimed.reward_coins
                        helpers.grant_trainer_xp(user, claimed.reward_xp)
                        claimed_now.append(claimed)
            state = quest_state(user)

        lines = []
        for q, current, done, was_claimed in state:
            bar = "✅" if (done and was_claimed) else ("🎁" if done else "⬜")
            lines.append(
                f"{bar} **{q.description}** — {min(current, q.goal)}/{q.goal}\n"
                f"   ↳ Recompensa: {q.reward_coins} 🪙 + {q.reward_xp} XP"
            )

        emb = discord.Embed(
            title="📋 Missões Diárias",
            description="\n".join(lines),
            color=settings.color_default,
        )
        if claimed_now:
            total_c = sum(q.reward_coins for q in claimed_now)
            total_x = sum(q.reward_xp for q in claimed_now)
            emb.add_field(
                name="🎉 Recompensas coletadas!",
                value=f"+{total_c} 🪙 e +{total_x} XP por {len(claimed_now)} missão(ões).",
                inline=False,
            )
        emb.set_footer(text="As missões resetam todo dia à meia-noite (UTC).")
        await ctx.send(embed=emb)

    # ------------------------------------------------------------------
    @commands.command(name="achievements", aliases=["conquistas", "ach"])
    @commands.guild_only()
    async def achievements(self, ctx: commands.Context, membro: discord.Member | None = None) -> None:
        """Lista as conquistas (desbloqueadas e bloqueadas)."""
        alvo = membro or ctx.author
        async with session_scope() as session:
            user = await helpers.fetch_user(session, alvo.id)
            unlocked = set(user.achievements or [])
            values = {
                "total_caught": user.total_caught,
                "total_shiny": user.total_shiny,
                "battles_won": user.battles_won,
            }

        lines = []
        for ach in ACHIEVEMENTS:
            if ach.key in unlocked:
                lines.append(f"🏅 **{ach.name}** — {ach.description} ✅")
            else:
                prog = min(values.get(ach.metric, 0), ach.goal)
                lines.append(f"🔒 **{ach.name}** — {ach.description} ({prog}/{ach.goal})")

        emb = discord.Embed(
            title=f"🏆 Conquistas de {alvo.display_name} ({len(unlocked)}/{len(ACHIEVEMENTS)})",
            description="\n".join(lines),
            color=settings.color_default,
        )
        await ctx.send(embed=emb)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Progression(bot))
