"""Batalha por turnos com TIME (até 3) e troca: PvP (battle) e PvE (duel)."""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass

import discord
from discord.ext import commands

log = logging.getLogger("pokebot")

from config import settings
from bot.data.gyms import party_slots
from bot.data.moves import MOVES, Move, get_move
from bot.data.pokemon_data import POKEDEX, Species
from bot.data.types import TYPE_EMOJI, effectiveness
from bot.database.db import session_scope
from bot.database.models import Pokemon
from bot.game.battle_engine import (
    BattleMon,
    apply_move,
    apply_rarity_bonus,
    build_battle_mon,
    can_act,
    effective_speed,
    end_of_turn,
)
from bot.utils import embeds, helpers
from bot.utils.battle_scene import render_battle_scene
from bot.utils.confirm import Confirm
from bot.utils.progression import bump_quest, check_achievements
from bot.utils.rarity import RARITY_WEIGHTS
from bot.utils.stats import apply_xp, compute_all_stats, max_hp

PARTY_MAX = 3


def hp_bar(fraction: float, size: int = 12) -> str:
    filled = round(fraction * size)
    if fraction > 0.5:
        block = "🟩"
    elif fraction > 0.25:
        block = "🟨"
    else:
        block = "🟥"
    return block * filled + "⬛" * (size - filled)


def team_dots(team: list[BattleMon], active: int) -> str:
    parts = []
    for i, m in enumerate(team):
        if not m.alive:
            parts.append("⚫")
        elif i == active:
            parts.append("🔵")
        else:
            parts.append("🟢")
    return "".join(parts)


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


def make_wild(species: Species, level: int, perfect: bool = False) -> WildMon:
    # IVs do selvagem ficam um pouco abaixo do teto (perfect=True -> 31, p/ líderes endgame)
    iv = (lambda: 31) if perfect else (lambda: random.randint(0, 25))
    return WildMon(
        id=-1, species_id=species.id, level=level, nature="Hardy", shiny=False,
        iv_hp=iv(), iv_atk=iv(), iv_def=iv(), iv_spa=iv(), iv_spd=iv(), iv_spe=iv(),
    )


def balanced_wild_level(player_level: int, player_bst: int, wild_bst: int,
                        factor: float = 1.0) -> int:
    """Nível do selvagem ajustado pela força (BST): espécie forte vem em nível menor."""
    ratio = player_bst / max(wild_bst, 1)
    return max(1, round(player_level * min(1.0, ratio) * factor))


def pick_balanced_wild_species(lead_species: Species, band: int = 70) -> Species:
    """Sorteia um selvagem de força (BST) parecida com o líder do jogador.

    Preferimos não-lendários; mas se o líder for de topo (Arceus, etc.), quase
    não há não-lendários nessa faixa — então liberamos lendários/míticos para
    dar variedade e um desafio à altura (senão cai sempre no mesmo Slaking).
    """
    target = lead_species.base_total
    pool = [s for s in POKEDEX.all() if s.id != lead_species.id]

    # 1ª tentativa: não-lendários numa banda de BST parecida
    cands = [s for s in pool if not s.legendary and abs(s.base_total - target) <= band]
    # 2ª: poucos candidatos → permite lendários/míticos na mesma banda
    if len(cands) < 6:
        cands = [s for s in pool if abs(s.base_total - target) <= band]
    # 3ª: ainda poucos → os 24 mais próximos em BST (garante variedade real)
    if len(cands) < 6:
        cands = sorted(pool, key=lambda s: abs(s.base_total - target))[:24]
    return random.choice(cands)


def build_wild_mon(species: Species, level: int, name: str | None = None,
                   shiny: bool = False, perfect_iv: bool = False) -> BattleMon:
    """Cria um BattleMon para um encontro selvagem (PvE/exploração)."""
    wild = make_wild(species, level, perfect=perfect_iv)
    stats = compute_all_stats(species, wild)
    mhp = max_hp(species, wild)
    stats, mhp = apply_rarity_bonus(stats, mhp, species.rarity)
    moves = [get_move(k) for k in species.moves if get_move(k)]
    return BattleMon(
        species=species, level=level, name=name or f"{species.name} selvagem",
        owner_id=None, pokemon_db_id=None, shiny=shiny,
        base_stats=stats, moves=(moves or [MOVES["tackle"]])[:4],
        max_hp=mhp,
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


# ==========================================================================
#  View de batalha com TIME e troca
# ==========================================================================
class BattleView(discord.ui.View):
    def __init__(self, cog: "Battle", ctx, p1_team: list[BattleMon], p2_team: list[BattleMon],
                 p1_id: int, p2_id: int | None, on_finish=None,
                 battle_channel=None, temp_channel=None, opponent_name=None, end_view=None):
        super().__init__(timeout=180)
        self.cog = cog
        self.ctx = ctx
        # se definido, ao fim da batalha a mensagem troca para esta View (ex.: voltar
        # ao hub com botão "Duelar de novo"). Usado nas batalhas privadas do /menu.
        self.end_view = end_view
        # canal onde a batalha é postada (pode ser uma arena privada)
        self.battle_channel = battle_channel or ctx.channel
        # se definido, esse canal é deletado 10s após o fim
        self.temp_channel = temp_channel
        self.p1_team = p1_team
        self.p2_team = p2_team
        self.p1_active = 0
        self.p2_active = 0
        self.p1_id = p1_id
        self.p2_id = p2_id            # None => PvE
        self.is_pve = p2_id is None
        self.on_finish = on_finish
        self.phase = "act_p1"         # act_p1/act_p2/sw_p1/sw_p2/fsw_p1/fsw_p2
        self.action_p1: tuple | None = None   # ('move', Move) | ('switch', idx)
        self.action_p2: tuple | None = None
        self._pending_fsw: list[str] = []
        self.turn = 1
        self.log: list[str] = ["A batalha começou!"]
        self.message: discord.Message | None = None
        self.finished = False

        guild = ctx.guild
        m1 = guild.get_member(p1_id) if p1_id else None
        self._names = {
            "p1": m1.display_name if m1 else "Treinador 1",
            "p2": (opponent_name or ("Selvagem" if self.is_pve
                   else (guild.get_member(p2_id).display_name if guild.get_member(p2_id) else "Treinador 2"))),
        }
        self._build()

    # ---- acesso ao mon ativo ----
    @property
    def p1(self) -> BattleMon:
        return self.p1_team[self.p1_active]

    @property
    def p2(self) -> BattleMon:
        return self.p2_team[self.p2_active]

    def _phase_side(self) -> str:
        return "p1" if self.phase.endswith("p1") else "p2"

    def _actor_id(self) -> int | None:
        return self.p1_id if self._phase_side() == "p1" else self.p2_id

    def _team(self, side: str):
        return (self.p1_team, self.p1_active) if side == "p1" else (self.p2_team, self.p2_active)

    @staticmethod
    def _reserves(team: list[BattleMon], active: int) -> list[tuple[int, BattleMon]]:
        return [(i, m) for i, m in enumerate(team) if m.alive and i != active]

    # ---- construção dos botões ----
    def _build(self) -> None:
        self.clear_items()
        if self.phase in ("act_p1", "act_p2"):
            side = self._phase_side()
            mon = self.p1 if side == "p1" else self.p2
            for mv in mon.moves:
                self.add_item(MoveButton(mv, self, disabled=mon.pp.get(mv.key, 0) <= 0))
            team, active = self._team(side)
            if self._reserves(team, active):
                self.add_item(TrocaButton(self))
            self.add_item(ForfeitButton(self))
        elif self.phase.startswith(("sw_", "fsw_")):
            forced = self.phase.startswith("fsw_")
            side = self._phase_side()
            team, active = self._team(side)
            for idx, mon in self._reserves(team, active):
                self.add_item(ReserveButton(idx, mon, self, forced))
            if not forced:
                self.add_item(VoltarButton(self))

    # ---- renderização ----
    def render(self, scene: bool = False) -> discord.Embed:
        emb = discord.Embed(title="⚔️ Batalha Pokémon", color=settings.color_default)
        for side in ("p1", "p2"):
            mon = self.p1 if side == "p1" else self.p2
            team, active = self._team(side)
            types = " ".join(TYPE_EMOJI.get(t, "") for t in mon.species.types)
            status = f" • {mon.status}" if mon.status else ""
            shiny = "✨" if mon.shiny else ""
            if scene:
                # a imagem já mostra HP, nível e o time — aqui só o que falta nela
                emb.add_field(
                    name=f"{shiny}{mon.name} {types}",
                    value=f"`{self._names[side]}`{status}",
                    inline=True,
                )
            else:
                emb.add_field(
                    name=f"{shiny}{mon.name} {types}",
                    value=(f"`{self._names[side]}`\n"
                           f"Nv {mon.level}{status}\n"
                           f"{hp_bar(mon.hp_fraction())}\n"
                           f"**{mon.hp}/{mon.max_hp}** HP\n"
                           f"Time: {team_dots(team, active)}"),
                    inline=True,
                )
        if scene:
            # cena composta (fundo + sprites + HP) enviada como anexo
            emb.set_image(url="attachment://scene.png")
        else:
            # fallback: sprites animados (oponente grande, o seu como miniatura)
            emb.set_image(url=settings.sprite_animated(self.p2.species.id, self.p2.shiny))
            emb.set_thumbnail(url=settings.sprite_animated(self.p1.species.id, self.p1.shiny))
        emb.add_field(name=f"📜 Turno {self.turn}", value="\n".join(self.log[-6:]) or "—", inline=False)
        if not self.finished:
            actor = self._actor_id()
            member = self.ctx.guild.get_member(actor) if actor else None
            nome = member.display_name if member else ("IA" if actor is None else "Jogador")
            if self.phase.startswith("fsw_"):
                emb.set_footer(text=f"{nome}: escolha o próximo pokémon!")
            elif self.phase.startswith("sw_"):
                emb.set_footer(text=f"{nome} está trocando...")
            else:
                emb.set_footer(text=f"Vez de {nome} — escolha um golpe ou troque.")
        return emb

    async def _render(self, banner=None, banner_color=None
                      ) -> tuple[discord.Embed, discord.File | None]:
        """Gera a cena (imagem) + o embed. Se a cena falhar, usa o visual antigo."""
        buf = await render_battle_scene(
            self.p1, self.p2, self.p1_team, self.p2_team,
            banner=banner, banner_color=banner_color)
        file = discord.File(buf, filename="scene.png") if buf is not None else None
        return self.render(scene=file is not None), file

    async def start(self) -> None:
        content = None
        if self.p2_id is not None:
            content = f"<@{self.p1_id}> ⚔️ <@{self.p2_id}> — que vença o melhor!"
        emb, file = await self._render()
        self.message = await self.battle_channel.send(
            content=content, embed=emb, view=self, **({"file": file} if file else {}))

    async def start_hosted(self, interaction: discord.Interaction) -> None:
        """Inicia a batalha EDITANDO a mensagem da interação (ex.: o /menu ephemeral).

        Assim o duelo PvE fica privado (só o jogador vê) e na mesma mensagem.
        """
        emb, file = await self._render()
        attachments = [file] if file else []
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=emb, view=self, attachments=attachments)
        else:
            await interaction.response.edit_message(embed=emb, view=self, attachments=attachments)
        try:
            self.message = await interaction.original_response()
        except discord.HTTPException:
            pass

    async def _cleanup_channel(self) -> None:
        """Apaga a arena privada 10s após o fim da batalha."""
        if self.temp_channel is None:
            return
        try:
            await self.temp_channel.send("🏁 A batalha acabou! Esta arena some em **10 segundos**...")
            await asyncio.sleep(10)
            await self.temp_channel.delete(reason="Fim da batalha PvP")
        except discord.HTTPException:
            pass

    async def _safe_edit(self, interaction: discord.Interaction) -> None:
        emb, file = await self._render()
        await interaction.response.edit_message(
            embed=emb, view=self, attachments=([file] if file else []))

    # ---- escolha de ação (golpe) ----
    async def on_action(self, interaction: discord.Interaction, action: tuple) -> None:
        if interaction.user.id != self._actor_id():
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        side = self._phase_side()
        if side == "p1":
            self.action_p1 = action
            if self.is_pve:
                self.action_p2 = ("move", ai_choose_move(self.p2, self.p1))
                await self._resolve(interaction)
            else:
                self.phase = "act_p2"
                self._build()
                await self._safe_edit(interaction)
        else:
            self.action_p2 = action
            await self._resolve(interaction)

    async def on_troca(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self._actor_id():
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        self.phase = f"sw_{self._phase_side()}"
        self._build()
        await self._safe_edit(interaction)

    async def on_voltar(self, interaction: discord.Interaction) -> None:
        self.phase = f"act_{self._phase_side()}"
        self._build()
        await self._safe_edit(interaction)

    async def on_switch_choice(self, interaction: discord.Interaction, idx: int) -> None:
        if interaction.user.id != self._actor_id():
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        side = self._phase_side()
        action = ("switch", idx)
        if side == "p1":
            self.action_p1 = action
            if self.is_pve:
                self.action_p2 = ("move", ai_choose_move(self.p2, self.p1))
                await self._resolve(interaction)
            else:
                self.phase = "act_p2"
                self._build()
                await self._safe_edit(interaction)
        else:
            self.action_p2 = action
            await self._resolve(interaction)

    async def on_forced_switch(self, interaction: discord.Interaction, idx: int) -> None:
        if interaction.user.id != self._actor_id():
            await interaction.response.send_message("Não é sua vez!", ephemeral=True)
            return
        side = self._phase_side()
        self._do_switch(side, idx, forced=True)
        if side in self._pending_fsw:
            self._pending_fsw.remove(side)
        await self._continue_forced(interaction)

    # ---- mecânica ----
    def _do_switch(self, side: str, idx: int, forced: bool = False) -> None:
        if side == "p1":
            old = self.p1.name
            self.p1_active = idx
            new = self.p1.name
        else:
            old = self.p2.name
            self.p2_active = idx
            new = self.p2.name
        verb = "mandou" if forced else "recolheu e enviou"
        if forced:
            self.log.append(f"🔄 {self._names[side]} mandou **{new}**!")
        else:
            self.log.append(f"🔄 {self._names[side]} recolheu **{old}** e enviou **{new}**!")

    def _apply_round(self) -> None:
        """Resolve um turno (trocas + ataques + status). Sem Discord — testável."""
        log: list[str] = []
        self.log = log  # _do_switch também grava aqui
        acts = {"p1": self.action_p1, "p2": self.action_p2}

        # 1) trocas acontecem primeiro
        for side in ("p1", "p2"):
            a = acts[side]
            if a and a[0] == "switch":
                self._do_switch(side, a[1], forced=False)

        # 2) ataques em ordem de prioridade/velocidade
        attackers = [(s, a[1]) for s, a in acts.items() if a and a[0] == "move"]

        def sort_key(item):
            s, mv = item
            mon = self.p1 if s == "p1" else self.p2
            return (mv.priority, effective_speed(mon))

        attackers.sort(key=sort_key, reverse=True)
        for s, mv in attackers:
            attacker = self.p1 if s == "p1" else self.p2
            defender = self.p2 if s == "p1" else self.p1
            if not attacker.alive or not defender.alive:
                continue
            ok, alog = can_act(attacker)
            log.extend(alog)
            if not ok:
                continue
            log.extend(apply_move(attacker, defender, mv))
            if not defender.alive:
                log.append(f"☠️ **{defender.name}** desmaiou!")

        # 3) status de fim de turno
        for mon in (self.p1, self.p2):
            log.extend(end_of_turn(mon))

        self.turn += 1
        self.action_p1 = self.action_p2 = None

    async def _resolve(self, interaction: discord.Interaction) -> None:
        self._apply_round()
        # play-by-play SÓ na arena privada (PvP). No PvE (temp_channel=None) nada é
        # enviado — o embed da cena já atualiza no lugar, sem poluir o canal.
        if self.temp_channel is not None and self.log:
            try:
                await self.battle_channel.send("📣 " + " ".join(self.log))
            except discord.HTTPException:
                pass
        await self._post_resolve(interaction)

    async def _post_resolve(self, interaction: discord.Interaction) -> None:
        p1_alive = any(m.alive for m in self.p1_team)
        p2_alive = any(m.alive for m in self.p2_team)
        if not p1_alive or not p2_alive:
            await self._end(interaction)
            return
        self._pending_fsw = [s for s in ("p1", "p2")
                             if not (self.p1 if s == "p1" else self.p2).alive]
        await self._continue_forced(interaction)

    async def _continue_forced(self, interaction: discord.Interaction) -> None:
        """Processa trocas forçadas (IA automática; humano via botões)."""
        while self._pending_fsw:
            side = self._pending_fsw[0]
            if side == "p2" and self.is_pve:
                team, active = self._team(side)
                reserves = self._reserves(team, active)
                if reserves:
                    self._do_switch(side, reserves[0][0], forced=True)
                self._pending_fsw.pop(0)
                continue
            # humano: mostra botões de troca forçada
            self.phase = f"fsw_{side}"
            self._build()
            await self._safe_edit(interaction)
            return
        # ninguém mais precisa trocar -> novo turno
        self.phase = "act_p1"
        self._build()
        await self._safe_edit(interaction)

    async def _end(self, interaction: discord.Interaction) -> None:
        self.finished = True
        p1_alive = any(m.alive for m in self.p1_team)
        winner_side = "p1" if p1_alive else "p2"
        winner_team = self.p1_team if winner_side == "p1" else self.p2_team
        loser_team = self.p2_team if winner_side == "p1" else self.p1_team
        winner_id = self.p1_id if winner_side == "p1" else self.p2_id
        loser_id = self.p2_id if winner_side == "p1" else self.p1_id
        winner_rep = next((m for m in winner_team if m.alive), winner_team[0])
        loser_rep = loser_team[self.p2_active if winner_side == "p1" else self.p1_active]

        self.clear_items()
        # banner na cena: VITÓRIA/DERROTA no PvE; nome do vencedor no PvP
        if self.is_pve:
            won_p1 = winner_side == "p1"
            banner = "VITÓRIA!" if won_p1 else "DERROTA"
            bcolor = (96, 220, 112) if won_p1 else (236, 92, 82)
        else:
            banner = f"{self._names[winner_side]} VENCEU!"
            bcolor = (255, 212, 92)
        emb, file = await self._render(banner=banner, banner_color=bcolor)
        emb.title = "🏆 Fim da batalha!"
        emb.color = settings.color_success
        result = await self.cog.award(winner_id, winner_team, loser_rep, self.is_pve, loser_id)
        emb.add_field(name="Resultado", value=result, inline=False)
        # batalha privada (hub): troca para a View de fim (botões Duelar de novo / Menu)
        final_view = self.end_view if self.end_view is not None else self
        if self.end_view is not None:
            self.end_view.message = self.message
        await interaction.response.edit_message(
            embed=emb, view=final_view, attachments=([file] if file else []))
        if self.on_finish is not None:
            try:
                await self.on_finish(winner_rep, loser_rep)
            except Exception:  # noqa: BLE001
                pass
        if self.temp_channel is not None:
            asyncio.create_task(self._cleanup_channel())
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
        if self.temp_channel is not None:
            asyncio.create_task(self._cleanup_channel())


class MoveButton(discord.ui.Button):
    def __init__(self, move: Move, view: BattleView, disabled: bool):
        mon = view.p1 if view.phase == "act_p1" else view.p2
        super().__init__(label=f"{move.name} ({mon.pp.get(move.key, 0)})"[:80],
                         emoji=TYPE_EMOJI.get(move.type),
                         style=discord.ButtonStyle.primary, disabled=disabled)
        self.move = move
        self._bv = view

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._bv.on_action(interaction, ("move", self.move))


class TrocaButton(discord.ui.Button):
    def __init__(self, view: BattleView):
        super().__init__(label="Trocar", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
        self._bv = view

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._bv.on_troca(interaction)


class ReserveButton(discord.ui.Button):
    def __init__(self, idx: int, mon: BattleMon, view: BattleView, forced: bool):
        shiny = "✨" if mon.shiny else ""
        super().__init__(label=f"{shiny}{mon.name} (Nv {mon.level})"[:80],
                         style=discord.ButtonStyle.success)
        self.idx = idx
        self.forced = forced
        self._bv = view

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.forced:
            await self._bv.on_forced_switch(interaction, self.idx)
        else:
            await self._bv.on_switch_choice(interaction, self.idx)


class VoltarButton(discord.ui.Button):
    def __init__(self, view: BattleView):
        super().__init__(label="Voltar", emoji="↩️", style=discord.ButtonStyle.secondary, row=1)
        self._bv = view

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._bv.on_voltar(interaction)


class ForfeitButton(discord.ui.Button):
    def __init__(self, view: BattleView):
        super().__init__(label="Desistir", style=discord.ButtonStyle.danger, row=1)
        self._bv = view

    async def callback(self, interaction: discord.Interaction) -> None:
        v = self._bv
        uid = interaction.user.id
        if uid == v.p1_id:
            for m in v.p1_team:
                m.hp = 0
        elif uid == v.p2_id:
            for m in v.p2_team:
                m.hp = 0
        else:
            await interaction.response.send_message("Você não está nesta batalha.", ephemeral=True)
            return
        v.log.append(f"🏳️ {interaction.user.display_name} desistiu!")
        await v._end(interaction)


# ==========================================================================
#  Cog
# ==========================================================================
class Battle(commands.Cog, name="Batalha"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    async def load_team(self, ctx, member) -> tuple[list[BattleMon], str]:
        """Carrega o time do membro (party) ou, na falta, o selecionado."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, member.id)
            team: list[BattleMon] = []
            for idx in list(user.party or []):
                poke = await helpers.get_pokemon_by_idx(session, user.id, idx)
                if poke:
                    sp = POKEDEX.get(poke.species_id)
                    team.append(build_battle_mon(
                        sp, poke, embeds.species_name(sp, poke.shiny, poke.nickname), member.id))
            if not team:
                poke = await helpers.get_selected(session, user)
                if poke is None:
                    return [], (f"{member.display_name} não tem pokémon para batalhar. "
                                f"Use `{ctx.prefix}select <#>` ou monte um time com `{ctx.prefix}party add <#>`.")
                sp = POKEDEX.get(poke.species_id)
                team = [build_battle_mon(
                    sp, poke, embeds.species_name(sp, poke.shiny, poke.nickname), member.id)]
        return team, ""

    async def load_selected(self, ctx, member) -> tuple[BattleMon | None, str]:
        """Compatibilidade: carrega apenas o pokémon selecionado."""
        team, err = await self.load_team(ctx, member)
        return (team[0] if team else None), err

    async def launch_battle(self, ctx, p1_team, p2_team, p1_id, p2_id, on_finish=None,
                            battle_channel=None, temp_channel=None, opponent_name=None) -> BattleView:
        view = BattleView(self, ctx, p1_team, p2_team, p1_id, p2_id, on_finish=on_finish,
                          battle_channel=battle_channel, temp_channel=temp_channel,
                          opponent_name=opponent_name)
        await view.start()
        return view

    @staticmethod
    def _can_make_arena(guild) -> bool:
        # canal privado exige criar o canal (manage_channels) E aplicar
        # permissões customizadas (manage_roles). Administrator cobre os dois.
        p = guild.me.guild_permissions
        return p.administrator or (p.manage_channels and p.manage_roles)

    async def _create_arena(self, ctx, a: discord.Member, b: discord.Member):
        """Cria um canal de batalha privado (só os dois + bot). None se não puder."""
        if not self._can_make_arena(ctx.guild):
            return None
        me = ctx.guild.me
        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, embed_links=True, read_message_history=True),
            a: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            b: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        nome = f"batalha-{a.display_name}-vs-{b.display_name}"[:95]
        try:
            return await ctx.guild.create_text_channel(
                nome, overwrites=overwrites, category=ctx.channel.category,
                topic=f"Batalha PvP entre {a.display_name} e {b.display_name}",
                reason="Arena de batalha PvP (temporária)",
            )
        except discord.HTTPException as exc:
            log.warning("Falha ao criar arena PvP no servidor %s: %s", ctx.guild.id, exc)
            return None

    # ------------------------------------------------------------------
    @commands.command(name="duel", aliases=["pve", "wild"])
    @commands.guild_only()
    async def duel(self, ctx: commands.Context, oponente: discord.Member | None = None) -> None:
        """Batalha: sem @ = contra selvagem (PvE); com @membro = PvP."""
        if oponente is not None:
            await self._start_pvp(ctx, oponente)
            return
        p1_team, err = await self.load_team(ctx, ctx.author)
        if not p1_team:
            await ctx.send(embed=embeds.err_embed(err))
            return
        # inimigo de força parecida, nível ~igual (leve vantagem para o jogador)
        lead = p1_team[0]
        species = pick_balanced_wild_species(lead.species)
        level = max(1, lead.level - random.randint(0, 2))
        p2_team = [build_wild_mon(species, level)]
        await self.launch_battle(ctx, p1_team, p2_team, ctx.author.id, None)

    # ------------------------------------------------------------------
    @commands.command(name="battle", aliases=["duelar", "lutar"])
    @commands.guild_only()
    async def battle(self, ctx: commands.Context, oponente: discord.Member) -> None:
        """Desafia outro jogador para uma batalha PvP. Uso: battle @usuário."""
        await self._start_pvp(ctx, oponente)

    async def _start_pvp(self, ctx: commands.Context, oponente: discord.Member) -> None:
        if oponente.bot or oponente.id == ctx.author.id:
            await ctx.send(embed=embeds.err_embed(
                "Escolha **outro membro** para a batalha PvP. (Para lutar contra um selvagem, use `"
                f"{ctx.prefix}duel` sem marcar ninguém.)"))
            return
        p1_team, err1 = await self.load_team(ctx, ctx.author)
        if not p1_team:
            await ctx.send(embed=embeds.err_embed(err1))
            return
        p2_team, err2 = await self.load_team(ctx, oponente)
        if not p2_team:
            await ctx.send(embed=embeds.err_embed(err2))
            return

        confirm = Confirm(oponente.id, confirm_label="Aceitar ⚔️", cancel_label="Recusar")
        emb = embeds.info_text(
            f"{oponente.mention}, **{ctx.author.display_name}** te desafiou para um **PvP**!\n"
            f"Seu time: **{len(p2_team)}** pokémon vs **{len(p1_team)}** do desafiante.",
            title="⚔️ Desafio de batalha!",
        )
        confirm.message = await ctx.send(content=oponente.mention, embed=emb, view=confirm)
        await confirm.wait()
        if not confirm.value:
            await ctx.send(embed=embeds.info_text("Desafio recusado ou expirado. 🙅"))
            return

        # cria uma arena privada (precisa de 'Gerenciar Canais' + 'Gerenciar Cargos')
        arena = await self._create_arena(ctx, ctx.author, oponente)

        if arena is not None:
            # posta a batalha (com o menu) já na arena
            view = await self.launch_battle(
                ctx, p1_team, p2_team, ctx.author.id, oponente.id,
                battle_channel=arena, temp_channel=arena)
            # botão-link no canal original que leva direto à batalha
            url = (view.message.jump_url if view.message
                   else f"https://discord.com/channels/{ctx.guild.id}/{arena.id}")
            link_view = discord.ui.View(timeout=None)
            link_view.add_item(discord.ui.Button(
                label="Ir para a Arena", emoji="⚔️", style=discord.ButtonStyle.link, url=url))
            await ctx.send(
                content=f"{ctx.author.mention} ⚔️ {oponente.mention}",
                embed=embeds.ok_embed(
                    "Arena criada!",
                    "A batalha de vocês já está montada na **arena privada**. "
                    "Cliquem no botão abaixo para entrar!\n*(o canal é apagado 10s após o fim)*"),
                view=link_view)
        else:
            await ctx.send(embed=embeds.info_text(
                "⚠️ Para criar **arenas privadas**, preciso das permissões **Gerenciar Canais** "
                "e **Gerenciar Cargos** no cargo do bot (Config. do Servidor → Cargos → **PokeM1D**).\n"
                "Por enquanto, a batalha rola aqui mesmo.",
                title="Arena indisponível"))
            await self.launch_battle(ctx, p1_team, p2_team, ctx.author.id, oponente.id)

    # ------------------------------------------------------------------
    async def award(self, winner_id, winner_team, loser_rep, is_pve, loser_id) -> str:
        rarity_mult = 1.0 / max(RARITY_WEIGHTS.get(loser_rep.species.rarity, 100) / 100, 0.05)
        coins = int((loser_rep.level * 5 + 30) * min(rarity_mult, 12))
        poke_xp = loser_rep.level * 8 + 25
        lines = []

        if winner_id is not None:
            level_ups = 0
            newly = []
            async with session_scope() as session:
                user = await helpers.fetch_user(session, winner_id)
                user.coins += coins
                user.battles_won += 1
                user.battles_total += 1
                helpers.grant_trainer_xp(user, 30)
                bump_quest(user, "battle_win", 1)
                newly = check_achievements(user)
                user.coins += sum(a.reward_coins for a in newly)
                for mon in winner_team:
                    if mon.pokemon_db_id is not None:
                        poke = await session.get(Pokemon, mon.pokemon_db_id)
                        if poke is not None:
                            nl, nx, g = apply_xp(poke.level, poke.xp, poke_xp)
                            poke.level, poke.xp = nl, nx
                            level_ups += g
            lines.append("🏆 **Vitória!**")
            lines.append(f"💰 +{coins:,} PokéCoins • ⭐ +{poke_xp} XP por pokémon")
            if level_ups:
                lines.append(f"📈 Seu time subiu **{level_ups}** nível(is) no total!")
            if newly:
                lines.append("🏅 " + ", ".join(a.name for a in newly))
        else:
            lines.append("🏆 O pokémon selvagem venceu! Sem recompensa.")

        if loser_id is not None:
            async with session_scope() as session:
                luser = await helpers.fetch_user(session, loser_id)
                luser.battles_total += 1
                helpers.grant_trainer_xp(luser, 10)
        return "\n".join(lines)

    # ==================================================================
    #  TIME (party)
    # ==================================================================
    @commands.group(name="party", aliases=["time", "equipe"], invoke_without_command=True)
    @commands.guild_only()
    async def party(self, ctx: commands.Context) -> None:
        """Mostra seu time de batalha (até 3). Subcomandos: add, remove, set, clear."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            party = list(user.party or [])
            pmax = party_slots(user.badges)
            members, linhas = [], []
            for pos, idx in enumerate(party, 1):
                poke = await helpers.get_pokemon_by_idx(session, user.id, idx)
                if poke:
                    sp = POKEDEX.get(poke.species_id)
                    shiny = "✨" if poke.shiny else ""
                    lead = "👑 " if pos == 1 else ""
                    linhas.append(f"`{pos}.` {lead}{shiny}**{sp.name}** #{idx} • Nv {poke.level} • IV {poke.iv_percent:.0f}%")
                    members.append({
                        "species_id": sp.id, "shiny": poke.shiny, "name": sp.name,
                        "level": poke.level, "iv": poke.iv_percent, "idx": idx, "lead": pos == 1,
                    })
                else:
                    linhas.append(f"`{pos}.` *(pokémon #{idx} não existe mais)*")

        if not linhas:
            await ctx.send(embed=embeds.info_text(
                f"Seu time está vazio — as batalhas usam seu pokémon **selecionado**.\n"
                f"Monte um time com `{ctx.prefix}party add <número>` (até {pmax}).\n"
                f"👑 O **1º** do time é o **líder** (batalha primeiro e define o nível dos encontros).",
                title="🎒 Seu time",
            ))
            return

        emb = discord.Embed(
            title=f"🎒 Time de {ctx.author.display_name} ({len(members)}/{pmax})",
            color=settings.color_default,
        )
        # imagem visual do time (cards); cai pro texto se falhar
        from bot.utils.team_scene import render_team
        buf = await render_team(members)
        file = discord.File(buf, filename="team.png") if buf else None
        if file:
            emb.set_image(url="attachment://team.png")
            emb.description = "👑 O **líder** (1º) batalha primeiro e define o nível dos encontros."
        else:
            emb.description = "\n".join(linhas)
        emb.set_footer(text=f"{ctx.prefix}party add/remove <#> • {ctx.prefix}select <#> troca o líder • {ctx.prefix}party clear")
        await ctx.send(embed=emb, **({"file": file} if file else {}))

    @party.command(name="add", aliases=["adicionar"])
    async def party_add(self, ctx: commands.Context, *numeros: int) -> None:
        """Adiciona um ou mais pokémon ao time. Uso: party add <#> [<#> ...]."""
        if not numeros:
            await ctx.send(embed=embeds.err_embed("Informe o(s) número(s). Ex.: `party add 1 2 3`."))
            return
        added, skipped = [], []
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            party = list(user.party or [])
            pmax = party_slots(user.badges)
            for n in dict.fromkeys(numeros):  # remove duplicatas mantendo a ordem
                if len(party) >= pmax:
                    skipped.append(f"#{n} (time cheio: {pmax})")
                    continue
                if n in party:
                    skipped.append(f"#{n} (já no time)")
                    continue
                poke = await helpers.get_pokemon_by_idx(session, user.id, n)
                if poke is None:
                    skipped.append(f"#{n} (não é seu)")
                    continue
                party.append(n)
                added.append(n)
            user.party = party
            total = len(party)
        partes = []
        if added:
            partes.append("✅ Adicionados: " + ", ".join(f"#{n}" for n in added) + f" (time {total}/{pmax})")
        if skipped:
            partes.append("⚠️ Ignorados: " + ", ".join(skipped))
        msg = "\n".join(partes)
        await ctx.send(embed=(embeds.ok_embed("Time atualizado", msg) if added
                              else embeds.err_embed(msg or "Nada foi adicionado.")))

    @party.command(name="remove", aliases=["remover", "rem"])
    async def party_remove(self, ctx: commands.Context, numero: int) -> None:
        """Remove um pokémon do time. Uso: party remove <número>."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            party = list(user.party or [])
            if numero not in party:
                await ctx.send(embed=embeds.err_embed("Esse pokémon não está no time."))
                return
            party.remove(numero)
            user.party = party
        await ctx.send(embed=embeds.ok_embed("Removido", f"Pokémon #{numero} saiu do time."))

    @party.command(name="set", aliases=["definir"])
    async def party_set(self, ctx: commands.Context, *numeros: int) -> None:
        """Define o time inteiro de uma vez. Uso: party set 1 2 3."""
        numeros = list(dict.fromkeys(numeros))
        if not numeros:
            await ctx.send(embed=embeds.err_embed(f"Informe os números. Ex.: `{ctx.prefix}party set 1 2 3`."))
            return
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            numeros = numeros[:party_slots(user.badges)]  # respeita o limite por insígnias
            valid = []
            for n in numeros:
                if await helpers.get_pokemon_by_idx(session, user.id, n):
                    valid.append(n)
            if not valid:
                await ctx.send(embed=embeds.err_embed("Nenhum desses pokémon é seu."))
                return
            user.party = valid
        await ctx.send(embed=embeds.ok_embed(
            "Time definido!", "Novo time: " + ", ".join(f"#{n}" for n in valid)))

    @party.command(name="clear", aliases=["limpar"])
    async def party_clear(self, ctx: commands.Context) -> None:
        """Esvazia o time (volta a usar o pokémon selecionado)."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            user.party = []
        await ctx.send(embed=embeds.ok_embed("Time esvaziado", "As batalhas voltam a usar seu selecionado."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Battle(bot))
