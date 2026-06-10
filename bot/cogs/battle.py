"""Sistema de batalha por turnos: PvP (battle) e PvE (duel), com botões."""
from __future__ import annotations

import random
from dataclasses import dataclass

import discord
from discord.ext import commands

from config import settings
from bot.data.moves import MOVES, Move, get_move
from bot.data.pokemon_data import POKEDEX, Species
from bot.data.types import TYPE_EMOJI, effectiveness
from bot.database.db import session_scope
from bot.database.models import Pokemon
from bot.game.battle_engine import BattleMon, build_battle_mon, resolve_turn
from bot.utils import embeds, helpers
from bot.utils.confirm import Confirm
from bot.utils.progression import bump_quest, check_achievements
from bot.utils.rarity import RARITY_WEIGHTS
from bot.utils.stats import apply_xp, compute_all_stats, max_hp


def hp_bar(fraction: float, size: int = 12) -> str:
    filled = round(fraction * size)
    if fraction > 0.5:
        block = "🟩"
    elif fraction > 0.25:
        block = "🟨"
    else:
        block = "🟥"
    return block * filled + "⬛" * (size - filled)


@dataclass
class WildMon:
    """Stand-in de um Pokemon do banco para encontros selvagens (PvE)."""
    id: int
    species_id: int
    level: int
    nature: str
    shiny: bool
    iv_hp: int
    iv_atk: int
    iv_def: int
    iv_spa: int
    iv_spd: int
    iv_spe: int


def make_wild(species: Species, level: int) -> WildMon:
    iv = lambda: random.randint(0, 31)
    return WildMon(
        id=-1, species_id=species.id, level=level, nature="Hardy", shiny=False,
        iv_hp=iv(), iv_atk=iv(), iv_def=iv(), iv_spa=iv(), iv_spd=iv(), iv_spe=iv(),
    )


def build_wild_mon(species: Species, level: int, name: str | None = None,
                   shiny: bool = False) -> BattleMon:
    """Cria um BattleMon para um encontro selvagem (PvE/exploração)."""
    wild = make_wild(species, level)
    stats = compute_all_stats(species, wild)
    moves = [get_move(k) for k in species.moves if get_move(k)]
    return BattleMon(
        species=species, level=level, name=name or f"{species.name} selvagem",
        owner_id=None, pokemon_db_id=None, shiny=shiny,
        base_stats=stats, moves=(moves or [MOVES["tackle"]])[:4],
        max_hp=max_hp(species, wild),
    )


def ai_choose_move(attacker: BattleMon, defender: BattleMon) -> Move:
    """IA simples: escolhe o golpe de maior dano esperado."""
    best, best_score = None, -1.0
    for mv in attacker.moves:
        if attacker.pp.get(mv.key, 0) <= 0:
            continue
        if mv.category == "status":
            score = 10
        else:
            eff = effectiveness(mv.type, defender.species.types)
            stab = 1.5 if mv.type in attacker.species.types else 1.0
            score = mv.power * eff * stab
        score *= random.uniform(0.8, 1.2)
        if score > best_score:
            best, best_score = mv, score
    return best or attacker.moves[0]


class BattleView(discord.ui.View):
    def __init__(self, cog: "Battle", ctx, p1: BattleMon, p2: BattleMon,
                 p1_id: int, p2_id: int | None, on_finish=None):
        super().__init__(timeout=180)
        self.cog = cog
        self.ctx = ctx
        self.p1 = p1
        self.p2 = p2
        self.p1_id = p1_id
        self.p2_id = p2_id           # None => PvE
        self.is_pve = p2_id is None
        # callback async opcional chamado ao fim: on_finish(winner, loser)
        self.on_finish = on_finish
        self.phase = "p1"            # quem deve escolher
        self.m1: Move | None = None
        self.m2: Move | None = None
        self.turn = 1
        self.log: list[str] = ["A batalha começou!"]
        self.message: discord.Message | None = None
        self.finished = False
        self._build_buttons()

    # ---- helpers de UI ----
    def _current_id(self) -> int:
        return self.p1_id if self.phase == "p1" else (self.p2_id or self.p1_id)

    def _current_mon(self) -> BattleMon:
        return self.p1 if self.phase == "p1" else self.p2

    def _build_buttons(self) -> None:
        self.clear_items()
        mon = self._current_mon()
        for mv in mon.moves:
            self.add_item(MoveButton(mv, self, disabled=mon.pp.get(mv.key, 0) <= 0))
        self.add_item(ForfeitButton(self))

    def render(self) -> discord.Embed:
        emb = discord.Embed(title="⚔️ Batalha Pokémon", color=settings.color_default)
        for mon in (self.p1, self.p2):
            types = " ".join(TYPE_EMOJI.get(t, "") for t in mon.species.types)
            status = f" • {mon.status}" if mon.status else ""
            shiny = "✨" if mon.shiny else ""
            emb.add_field(
                name=f"{shiny}{mon.name} {types}",
                value=(f"Nv {mon.level}{status}\n"
                       f"{hp_bar(mon.hp_fraction())}\n"
                       f"**{mon.hp}/{mon.max_hp}** HP"),
                inline=True,
            )
        recent = "\n".join(self.log[-6:])
        emb.add_field(name=f"📜 Turno {self.turn}", value=recent or "—", inline=False)
        if not self.finished:
            chooser = self.ctx.guild.get_member(self._current_id())
            nome = chooser.display_name if chooser else "Jogador"
            emb.set_footer(text=f"Vez de {nome} escolher um golpe.")
        return emb

    async def start(self) -> None:
        self.message = await self.ctx.send(embed=self.render(), view=self)

    # ---- fluxo de turno ----
    async def on_move(self, interaction: discord.Interaction, move: Move) -> None:
        if interaction.user.id != self._current_id():
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return

        if self.phase == "p1":
            self.m1 = move
            if self.is_pve:
                self.m2 = ai_choose_move(self.p2, self.p1)
                await self._resolve(interaction)
            else:
                self.phase = "p2"
                self._build_buttons()
                await interaction.response.edit_message(embed=self.render(), view=self)
        else:  # phase p2
            self.m2 = move
            await self._resolve(interaction)

    async def _resolve(self, interaction: discord.Interaction) -> None:
        turn_log = resolve_turn(self.p1, self.m1, self.p2, self.m2)
        self.log = turn_log
        self.turn += 1
        self.m1 = self.m2 = None
        self.phase = "p1"

        if not self.p1.alive or not self.p2.alive:
            await self._end(interaction)
            return

        self._build_buttons()
        await interaction.response.edit_message(embed=self.render(), view=self)

    async def _end(self, interaction: discord.Interaction) -> None:
        self.finished = True
        winner = self.p1 if self.p1.alive else self.p2
        loser = self.p2 if winner is self.p1 else self.p1
        self.clear_items()

        emb = self.render()
        emb.title = "🏆 Fim da batalha!"
        emb.color = settings.color_success
        result = await self.cog.award(winner, loser, self.is_pve)
        emb.add_field(name="Resultado", value=result, inline=False)
        await interaction.response.edit_message(embed=emb, view=self)
        if self.on_finish is not None:
            try:
                await self.on_finish(winner, loser)
            except Exception:  # noqa: BLE001
                pass
        self.stop()

    async def on_timeout(self) -> None:
        if self.finished:
            return
        for c in self.children:
            c.disabled = True
        if self.message:
            try:
                await self.message.edit(content="⌛ A batalha expirou por inatividade.", view=self)
            except discord.HTTPException:
                pass


class MoveButton(discord.ui.Button):
    def __init__(self, move: Move, view: BattleView, disabled: bool):
        label = f"{move.name} ({view._current_mon().pp.get(move.key, 0)})"
        super().__init__(label=label[:80], style=discord.ButtonStyle.primary, disabled=disabled)
        self.move = move
        self._view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._view.on_move(interaction, self.move)


class ForfeitButton(discord.ui.Button):
    def __init__(self, view: BattleView):
        super().__init__(label="Desistir", style=discord.ButtonStyle.danger, row=1)
        self._view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        v = self._view
        if interaction.user.id not in (v.p1_id, v.p2_id):
            await interaction.response.send_message("Você não está nesta batalha.", ephemeral=True)
            return
        # quem desiste perde
        if interaction.user.id == v.p1_id:
            v.p1.hp = 0
        else:
            v.p2.hp = 0
        v.log.append(f"🏳️ {interaction.user.display_name} desistiu!")
        await v._end(interaction)


class Battle(commands.Cog, name="Batalha"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    async def load_selected(self, ctx, member) -> tuple[BattleMon | None, str]:
        """Carrega o pokémon selecionado de um membro como BattleMon."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, member.id)
            poke = await helpers.get_selected(session, user)
            if poke is None:
                return None, f"{member.display_name} não tem um pokémon selecionado (`{ctx.prefix}select <#>`)."
            sp = POKEDEX.get(poke.species_id)
            mon = build_battle_mon(sp, poke, embeds.species_name(sp, poke.shiny, poke.nickname), member.id)
        return mon, ""

    # compatibilidade interna
    _load_selected = load_selected

    async def launch_battle(self, ctx, p1: BattleMon, p2: BattleMon,
                            p1_id: int, p2_id: int | None, on_finish=None) -> "BattleView":
        """Inicia uma batalha e retorna a view (usado por outras cogs)."""
        view = BattleView(self, ctx, p1, p2, p1_id, p2_id, on_finish=on_finish)
        await view.start()
        return view

    # ------------------------------------------------------------------
    @commands.command(name="duel", aliases=["pve", "wild"])
    @commands.guild_only()
    async def duel(self, ctx: commands.Context) -> None:
        """Batalha contra um pokémon selvagem (PvE)."""
        p1, err = await self.load_selected(ctx, ctx.author)
        if p1 is None:
            await ctx.send(embed=embeds.err_embed(err))
            return

        # gera um oponente selvagem de nível parecido
        from bot.utils.rarity import pick_spawn_species
        species = pick_spawn_species()
        level = max(1, p1.level + random.randint(-3, 3))
        p2 = build_wild_mon(species, level)
        await self.launch_battle(ctx, p1, p2, ctx.author.id, None)

    # ------------------------------------------------------------------
    @commands.command(name="battle", aliases=["duelar", "lutar"])
    @commands.guild_only()
    async def battle(self, ctx: commands.Context, oponente: discord.Member) -> None:
        """Desafia outro jogador para uma batalha PvP. Uso: battle @usuário."""
        if oponente.bot or oponente.id == ctx.author.id:
            await ctx.send(embed=embeds.err_embed("Escolha outro jogador válido."))
            return

        p1, err1 = await self._load_selected(ctx, ctx.author)
        if p1 is None:
            await ctx.send(embed=embeds.err_embed(err1))
            return
        p2, err2 = await self._load_selected(ctx, oponente)
        if p2 is None:
            await ctx.send(embed=embeds.err_embed(err2))
            return

        # pedido de aceite
        confirm = Confirm(oponente.id, confirm_label="Aceitar ⚔️", cancel_label="Recusar")
        emb = embeds.info_text(
            f"{oponente.mention}, **{ctx.author.display_name}** te desafiou para uma batalha!\n"
            f"Seu **{p2.name}** (Nv {p2.level}) vs **{p1.name}** (Nv {p1.level}).",
            title="⚔️ Desafio de batalha!",
        )
        confirm.message = await ctx.send(content=oponente.mention, embed=emb, view=confirm)
        await confirm.wait()
        if not confirm.value:
            await ctx.send(embed=embeds.info_text("Desafio recusado ou expirado. 🙅"))
            return

        view = BattleView(self, ctx, p1, p2, ctx.author.id, oponente.id)
        await view.start()

    # ------------------------------------------------------------------
    async def award(self, winner: BattleMon, loser: BattleMon, is_pve: bool) -> str:
        """Concede recompensas ao vencedor e atualiza estatísticas."""
        rarity_mult = 1.0 / max(RARITY_WEIGHTS.get(loser.species.rarity, 100) / 100, 0.05)
        coins = int((loser.level * 5 + 30) * min(rarity_mult, 12))
        poke_xp = loser.level * 8 + 25
        lines = []

        if winner.owner_id is not None:
            async with session_scope() as session:
                user = await helpers.fetch_user(session, winner.owner_id)
                user.coins += coins
                user.battles_won += 1
                user.battles_total += 1
                helpers.grant_trainer_xp(user, 30)
                bump_quest(user, "battle_win", 1)
                newly = check_achievements(user)
                user.coins += sum(a.reward_coins for a in newly)

                # XP para o pokémon vencedor (se for do banco)
                level_up = 0
                if winner.pokemon_db_id is not None:
                    poke = await session.get(Pokemon, winner.pokemon_db_id)
                    if poke is not None:
                        nl, nx, gained = apply_xp(poke.level, poke.xp, poke_xp)
                        poke.level, poke.xp, level_up = nl, nx, gained

            lines.append(f"🏆 **{winner.name}** venceu!")
            lines.append(f"💰 +{coins:,} PokéCoins • ⭐ +{poke_xp} XP")
            if level_up:
                lines.append(f"📈 **{winner.name}** subiu {level_up} nível(is)!")
            if newly:
                lines.append("🏅 " + ", ".join(a.name for a in newly))
        else:
            lines.append(f"🏆 O **{winner.name}** selvagem venceu! Não houve recompensa.")

        # perdedor (se for jogador) registra a derrota
        if loser.owner_id is not None and not is_pve:
            async with session_scope() as session:
                luser = await helpers.fetch_user(session, loser.owner_id)
                luser.battles_total += 1
                helpers.grant_trainer_xp(luser, 10)
        elif loser.owner_id is not None and is_pve:
            async with session_scope() as session:
                luser = await helpers.fetch_user(session, loser.owner_id)
                luser.battles_total += 1

        return "\n".join(lines)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Battle(bot))
