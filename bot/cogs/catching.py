"""Sistema de captura: adivinhe o nome do pokémon que apareceu."""
from __future__ import annotations

import discord
from discord.ext import commands

from config import settings
from bot.data.pokemon_data import normalize_name
from bot.database.db import session_scope
from bot.utils import embeds, helpers
from bot.utils.progression import bump_quest, check_achievements
from bot.utils.rarity import catch_coin_reward


class Catching(commands.Cog, name="Captura"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="catch", aliases=["c", "capturar"])
    @commands.cooldown(1, 1.5, commands.BucketType.user)
    @commands.guild_only()
    async def catch(self, ctx: commands.Context, *, palpite: str) -> None:
        """Captura o pokémon selvagem ativo no canal. Uso: catch <nome>."""
        spawn = self.bot.active_spawns.get(ctx.channel.id)
        if spawn is None:
            await ctx.send(embed=embeds.err_embed(
                "Não há nenhum pokémon selvagem por aqui agora. Espere o próximo aparecer!"
            ))
            return

        if normalize_name(palpite) != normalize_name(spawn.species.name):
            # também aceita nomes alternativos
            from bot.data.pokemon_data import POKEDEX
            guessed = POKEDEX.by_name(palpite)
            if guessed is None or guessed.id != spawn.species.id:
                await ctx.send(f"❌ Esse não é o nome certo, {ctx.author.mention}! Tente de novo.")
                return

        # captura confirmada — remove o spawn imediatamente (evita corrida)
        self.bot.active_spawns.pop(ctx.channel.id, None)
        species = spawn.species
        shiny = spawn.shiny

        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)

            # captura do spawn é GRÁTIS (não gasta pokébola). Para usar bolas e
            # melhorar IV/chance, o jogador usa o p!explore -> Capturar.
            poke = await helpers.create_pokemon(session, user, species, shiny=shiny)

            coins = catch_coin_reward(species, shiny, settings.catch_coins_min, settings.catch_coins_max)
            user.coins += coins
            user.total_caught += 1
            if shiny:
                user.total_shiny += 1

            helpers.grant_trainer_xp(user, settings.catch_xp)
            new_dex = await helpers.update_pokedex(session, user.id, species.id, seen=1, caught=1)

            bump_quest(user, "catch", 1)
            if shiny:
                bump_quest(user, "shiny", 1)
            newly = check_achievements(user)

        embed = embeds.catch_embed(species, poke, ctx.author.display_name, coins, shiny, new_dex)
        await ctx.send(embed=embed)

        # anuncia no canal de warning se for raro/shiny
        await self.bot.announce_rare(ctx.guild, ctx.author, species, shiny, poke.level)

        # edita a mensagem do spawn para indicar que foi capturado
        if spawn.message_id:
            try:
                msg = await ctx.channel.fetch_message(spawn.message_id)
                done = discord.Embed(
                    description=f"✅ **{ctx.author.display_name}** capturou o "
                                f"{'✨ ' if shiny else ''}**{species.name}**!",
                    color=settings.color_success,
                )
                await msg.edit(embed=done)
            except discord.HTTPException:
                pass

        # anuncia conquistas desbloqueadas
        if newly:
            linhas = "\n".join(f"🏆 **{a.name}** — {a.description} (+{a.reward_coins} 🪙)" for a in newly)
            await ctx.send(embed=embeds.ok_embed("Conquista desbloqueada!", linhas))
            # credita as recompensas das conquistas
            async with session_scope() as session:
                user = await helpers.fetch_user(session, ctx.author.id)
                user.coins += sum(a.reward_coins for a in newly)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Catching(bot))
