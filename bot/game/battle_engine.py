"""Motor de batalha por turnos (sem dependência do Discord)."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from bot.data.moves import MOVES, Move, get_move
from bot.data.pokemon_data import Species
from bot.data.types import effectiveness, effectiveness_label
from bot.utils.stats import compute_all_stats, max_hp

STAGE_KEYS = ["atk", "def", "spa", "spd", "spe"]

# Bônus de stats em batalha por raridade (raridade = poder real, além do BST).
RARITY_BATTLE_MULT = {
    "common": 1.0, "uncommon": 1.0, "rare": 1.03,
    "superrare": 1.07, "legendary": 1.15, "mythical": 1.22,
}


def apply_rarity_bonus(stats: dict[str, int], hp: int, rarity: str) -> tuple[dict[str, int], int]:
    m = RARITY_BATTLE_MULT.get(rarity, 1.0)
    if m == 1.0:
        return stats, hp
    return {k: int(v * m) for k, v in stats.items()}, int(hp * m)


def stage_multiplier(stage: int) -> float:
    stage = max(-6, min(6, stage))
    if stage >= 0:
        return (2 + stage) / 2
    return 2 / (2 - stage)


@dataclass
class BattleMon:
    species: Species
    level: int
    name: str
    owner_id: int | None          # discord id (None = IA)
    pokemon_db_id: int | None     # id na tabela Pokemon (None = selvagem)
    shiny: bool
    base_stats: dict[str, int]    # atributos calculados
    moves: list[Move]
    max_hp: int
    hp: int = field(init=False)
    pp: dict[str, int] = field(init=False)
    stages: dict[str, int] = field(default_factory=lambda: {k: 0 for k in STAGE_KEYS})
    status: str | None = None     # burn | poison | paralyze | sleep | freeze
    sleep_turns: int = 0
    held_item: str | None = None  # item segurado (ex.: mega-stone) — lido de pokemon.held_item
    stat_source: object | None = None  # objeto com iv_*/nature/level p/ recalcular na Mega
    is_mega: bool = False         # já Mega Evoluiu nesta batalha
    mega_label: str | None = None  # nome da forma Mega (p/ exibição)

    def __post_init__(self) -> None:
        self.hp = self.max_hp
        self.pp = {m.key: m.pp for m in self.moves}

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def eff_stat(self, key: str) -> int:
        if key == "hp":
            return self.max_hp
        return max(1, int(self.base_stats[key] * stage_multiplier(self.stages.get(key, 0))))

    def hp_fraction(self) -> float:
        return max(0.0, self.hp / self.max_hp)


def build_battle_mon(
    species: Species, pokemon, name: str, owner_id: int | None
) -> BattleMon:
    """Cria um BattleMon a partir de um registro Pokemon do banco."""
    stats = compute_all_stats(species, pokemon)
    mhp = max_hp(species, pokemon)
    stats, mhp = apply_rarity_bonus(stats, mhp, species.rarity)
    moves = [get_move(k) for k in species.moves if get_move(k)]
    if not moves:
        moves = [MOVES["tackle"]]
    return BattleMon(
        species=species, level=pokemon.level, name=name,
        owner_id=owner_id, pokemon_db_id=pokemon.id, shiny=pokemon.shiny,
        base_stats=stats, moves=moves[:4], max_hp=mhp,
        held_item=getattr(pokemon, "held_item", None), stat_source=pokemon,
    )


# ---------------------------------------------------------------------------
# Resolução de um golpe
# ---------------------------------------------------------------------------
def calc_damage(attacker: BattleMon, defender: BattleMon, move: Move) -> tuple[int, list[str]]:
    """Calcula o dano de um golpe. Retorna (dano, mensagens)."""
    log: list[str] = []
    if move.category == "status" or move.power <= 0:
        return 0, log

    if move.category == "physical":
        atk = attacker.eff_stat("atk")
        df = defender.eff_stat("def")
        if attacker.status == "burn":
            atk = atk // 2  # queimadura reduz ataque físico
    else:
        atk = attacker.eff_stat("spa")
        df = defender.eff_stat("spd")

    base = (((2 * attacker.level / 5 + 2) * move.power * (atk / df)) / 50) + 2

    # STAB
    stab = 1.5 if move.type in attacker.species.types else 1.0
    # efetividade de tipo
    eff = effectiveness(move.type, defender.species.types)
    if eff == 0:
        return 0, ["Não teve efeito..."]
    # crítico
    crit = 1.5 if random.random() < 1 / 16 else 1.0
    # variação
    rand = random.uniform(0.85, 1.0)

    dmg = int(base * stab * eff * crit * rand)
    dmg = max(1, dmg)

    if crit > 1:
        log.append("💥 Acerto crítico!")
    label = effectiveness_label(eff)
    if label:
        log.append(label)
    return dmg, log


def apply_move(attacker: BattleMon, defender: BattleMon, move: Move) -> list[str]:
    """Executa um golpe completo (precisão, dano, efeitos). Retorna o log."""
    log: list[str] = [f"**{attacker.name}** usou **{move.name}**!"]

    # PP
    if attacker.pp.get(move.key, 0) <= 0:
        log.append(f"...mas não há PP! ({move.name})")
        return log
    attacker.pp[move.key] -= 1

    # precisão (0 = nunca erra)
    if move.accuracy and random.randint(1, 100) > move.accuracy:
        log.append(f"Mas **{attacker.name}** errou!")
        return log

    # dano
    dmg, dmg_log = calc_damage(attacker, defender, move)
    log.extend(dmg_log)
    if dmg > 0:
        defender.hp = max(0, defender.hp - dmg)
        log.append(f"Causou **{dmg}** de dano. ({defender.name}: {defender.hp}/{defender.max_hp} HP)")

    # efeitos
    effect = move.effect or {}
    if effect:
        chance = effect.get("chance", 100)
        if random.randint(1, 100) <= chance:
            log.extend(_apply_effect(attacker, defender, effect))

    return log


def _apply_effect(attacker: BattleMon, defender: BattleMon, effect: dict) -> list[str]:
    log: list[str] = []
    # cura
    if "heal" in effect:
        healed = int(attacker.max_hp * effect["heal"])
        attacker.hp = min(attacker.max_hp, attacker.hp + healed)
        log.append(f"💚 **{attacker.name}** recuperou {healed} HP.")
    # status
    if "status" in effect:
        target = attacker if effect.get("self") else defender
        if target.status is None and target.alive:
            target.status = effect["status"]
            if effect["status"] == "sleep":
                target.sleep_turns = random.randint(1, 3)
            log.append(f"🌀 **{target.name}** ficou com *{_status_pt(effect['status'])}*!")
    # mudança de atributo
    if "stat" in effect:
        target = attacker if effect.get("self") else defender
        stat, delta = effect["stat"], effect["stage"]
        target.stages[stat] = max(-6, min(6, target.stages.get(stat, 0) + delta))
        seta = "aumentou" if delta > 0 else "diminuiu"
        log.append(f"📊 {stat.upper()} de **{target.name}** {seta}.")
    return log


def _status_pt(status: str) -> str:
    return {
        "burn": "queimadura", "poison": "envenenamento", "paralyze": "paralisia",
        "sleep": "sono", "freeze": "congelamento",
    }.get(status, status)


def can_act(mon: BattleMon) -> tuple[bool, list[str]]:
    """Verifica se o pokémon pode agir neste turno (status incapacitantes)."""
    log: list[str] = []
    if mon.status == "sleep":
        if mon.sleep_turns > 0:
            mon.sleep_turns -= 1
            log.append(f"😴 **{mon.name}** está dormindo...")
            return False, log
        mon.status = None
        log.append(f"**{mon.name}** acordou!")
    if mon.status == "freeze":
        if random.random() < 0.2:
            mon.status = None
            log.append(f"**{mon.name}** descongelou!")
        else:
            log.append(f"🧊 **{mon.name}** está congelado!")
            return False, log
    if mon.status == "paralyze" and random.random() < 0.25:
        log.append(f"⚡ **{mon.name}** está paralisado e não conseguiu se mover!")
        return False, log
    return True, log


def end_of_turn(mon: BattleMon) -> list[str]:
    """Dano de status no fim do turno."""
    log: list[str] = []
    if not mon.alive:
        return log
    if mon.status == "burn":
        dmg = max(1, mon.max_hp // 16)
        mon.hp = max(0, mon.hp - dmg)
        log.append(f"🔥 **{mon.name}** sofreu {dmg} de dano por queimadura.")
    elif mon.status == "poison":
        dmg = max(1, mon.max_hp // 8)
        mon.hp = max(0, mon.hp - dmg)
        log.append(f"☠️ **{mon.name}** sofreu {dmg} de dano por veneno.")
    return log


def effective_speed(mon: BattleMon) -> int:
    spe = mon.eff_stat("spe")
    if mon.status == "paralyze":
        spe = spe // 2
    return spe


# ---------------------------------------------------------------------------
# Itens de batalha (🎒 Mochila) — usar NÃO gasta o turno
# ---------------------------------------------------------------------------
def apply_battle_item(mon: BattleMon, item) -> tuple[bool, list[str]]:
    """Aplica um item de batalha ao pokémon ativo. Retorna (mudou_algo, log).

    Só consome o item se `mudou_algo` for True (item que não faz efeito não é gasto).
    """
    log: list[str] = []
    changed = False

    # cura de HP
    if item.heal and mon.alive:
        before = mon.hp
        mon.hp = mon.max_hp if item.heal < 0 else min(mon.max_hp, mon.hp + item.heal)
        if mon.hp > before:
            changed = True
            log.append(f"🧪 **{item.name}**: {mon.name} recuperou **{mon.hp - before}** HP.")

    # cura de status
    if item.cures and mon.status is not None:
        if "any" in item.cures or mon.status in item.cures:
            cured = mon.status
            mon.status = None
            mon.sleep_turns = 0
            changed = True
            log.append(f"💊 **{item.name}**: {mon.name} se curou de *{_status_pt(cured)}*.")

    # restaurar PP
    if item.pp_restore:
        if item.pp_all:
            targets = list(mon.moves)
        else:
            # golpe com mais PP faltando (o mais gasto)
            depleted = sorted(mon.moves, key=lambda mv: mon.pp.get(mv.key, 0) - mv.pp)
            targets = depleted[:1]
        touched = False
        for mv in targets:
            cur, mx = mon.pp.get(mv.key, 0), mv.pp
            if cur < mx:
                mon.pp[mv.key] = mx if item.pp_restore < 0 else min(mx, cur + item.pp_restore)
                touched = True
        if touched:
            changed = True
            alvo = "todos os golpes" if item.pp_all else "o golpe mais gasto"
            log.append(f"🔵 **{item.name}**: PP de {alvo} restaurado ({mon.name}).")

    # X-item (estágio de atributo)
    if item.battle_stat and mon.alive:
        key = item.battle_stat
        cur = mon.stages.get(key, 0)
        if cur < 6:
            mon.stages[key] = min(6, cur + item.battle_stage)
            changed = True
            log.append(f"📊 **{item.name}**: {key.upper()} de {mon.name} aumentou!")

    if not changed:
        log.append(f"...mas não teve efeito.")
    return changed, log


# ---------------------------------------------------------------------------
# Mega Evolução — transforma o ativo (1x/batalha); nada é salvo no banco
# ---------------------------------------------------------------------------
def can_mega(mon: BattleMon) -> bool:
    """True se o ativo segura a Mega Stone certa e ainda não Mega Evoluiu."""
    if mon.is_mega or not mon.held_item or mon.stat_source is None:
        return False
    from bot.data.mega import mega_for_stone
    form = mega_for_stone(mon.held_item)
    return form is not None and form.base_id == mon.species.id


def mega_evolve(mon: BattleMon) -> list[str]:
    """Aplica a Mega Evolução ao pokémon ativo. Retorna o log (vazio se não pôde)."""
    if not can_mega(mon):
        return []
    from bot.data.mega import mega_for_stone
    form = mega_for_stone(mon.held_item)
    if form is None:
        return []

    rarity = mon.species.rarity
    mega_sp = Species(
        id=form.mega_id, name=form.mega_name, types=list(form.types),
        base_stats=dict(form.base_stats), rarity=rarity,
        legendary=mon.species.legendary, mythical=mon.species.mythical,
    )
    stats = compute_all_stats(mega_sp, mon.stat_source)
    mhp = max_hp(mega_sp, mon.stat_source)
    stats, mhp = apply_rarity_bonus(stats, mhp, rarity)

    frac = mon.hp_fraction()
    mon.species = mega_sp
    mon.base_stats = stats
    mon.max_hp = mhp
    mon.hp = max(1, round(mhp * frac)) if frac > 0 else 0
    mon.is_mega = True
    mon.mega_label = form.mega_name
    return [f"✨ **{mon.name}** Mega Evoluiu em **{form.mega_name}**!"]


def resolve_turn(
    p1: BattleMon, m1: Move, p2: BattleMon, m2: Move
) -> list[str]:
    """Resolve um turno completo com os dois golpes escolhidos."""
    log: list[str] = []

    # ordem: prioridade do golpe, depois velocidade
    order = sorted(
        [(p1, m1, p2), (p2, m2, p1)],
        key=lambda t: (t[1].priority, effective_speed(t[0])),
        reverse=True,
    )

    for attacker, move, defender in order:
        if not attacker.alive or not defender.alive:
            continue
        act, act_log = can_act(attacker)
        log.extend(act_log)
        if not act:
            continue
        log.extend(apply_move(attacker, defender, move))
        if not defender.alive:
            log.append(f"☠️ **{defender.name}** desmaiou!")

    # fim de turno (status)
    for mon in (p1, p2):
        log.extend(end_of_turn(mon))
        if not mon.alive and f"**{mon.name}** desmaiou!" not in " ".join(log):
            log.append(f"☠️ **{mon.name}** desmaiou!")

    return log
