"""Registro de movimentos (golpes) usados no sistema de batalha."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Move:
    key: str
    name: str
    type: str
    category: str          # "physical" | "special" | "status"
    power: int             # 0 para golpes de status
    accuracy: int          # 0–100 (0 = nunca erra)
    pp: int
    priority: int = 0
    # efeito opcional aplicado após o golpe
    effect: dict = field(default_factory=dict)
    # exemplos de effect:
    #   {"heal": 0.5}                          -> cura 50% do HP máx
    #   {"stat": "atk", "stage": 1, "self": True}
    #   {"stat": "def", "stage": -1, "self": False}
    #   {"status": "burn", "chance": 30}


MOVES: dict[str, Move] = {
    # --------- Normal ---------
    "tackle": Move("tackle", "Tackle", "normal", "physical", 40, 100, 35),
    "scratch": Move("scratch", "Scratch", "normal", "physical", 40, 100, 35),
    "quick-attack": Move("quick-attack", "Quick Attack", "normal", "physical", 40, 100, 30, priority=1),
    "body-slam": Move("body-slam", "Body Slam", "normal", "physical", 85, 100, 15),
    "hyper-beam": Move("hyper-beam", "Hyper Beam", "normal", "special", 150, 90, 5),
    "swords-dance": Move("swords-dance", "Swords Dance", "normal", "status", 0, 0, 20,
                         effect={"stat": "atk", "stage": 2, "self": True}),
    "growl": Move("growl", "Growl", "normal", "status", 0, 100, 40,
                  effect={"stat": "atk", "stage": -1, "self": False}),
    "recover": Move("recover", "Recover", "normal", "status", 0, 0, 10,
                    effect={"heal": 0.5}),
    # --------- Fire ---------
    "ember": Move("ember", "Ember", "fire", "special", 40, 100, 25,
                  effect={"status": "burn", "chance": 10}),
    "flamethrower": Move("flamethrower", "Flamethrower", "fire", "special", 90, 100, 15,
                         effect={"status": "burn", "chance": 10}),
    "fire-blast": Move("fire-blast", "Fire Blast", "fire", "special", 110, 85, 5,
                       effect={"status": "burn", "chance": 30}),
    "fire-punch": Move("fire-punch", "Fire Punch", "fire", "physical", 75, 100, 15),
    # --------- Water ---------
    "water-gun": Move("water-gun", "Water Gun", "water", "special", 40, 100, 25),
    "bubble-beam": Move("bubble-beam", "Bubble Beam", "water", "special", 65, 100, 20),
    "surf": Move("surf", "Surf", "water", "special", 90, 100, 15),
    "hydro-pump": Move("hydro-pump", "Hydro Pump", "water", "special", 110, 80, 5),
    "aqua-tail": Move("aqua-tail", "Aqua Tail", "water", "physical", 90, 90, 10),
    # --------- Electric ---------
    "thunder-shock": Move("thunder-shock", "Thunder Shock", "electric", "special", 40, 100, 30,
                          effect={"status": "paralyze", "chance": 10}),
    "thunderbolt": Move("thunderbolt", "Thunderbolt", "electric", "special", 90, 100, 15,
                        effect={"status": "paralyze", "chance": 10}),
    "thunder": Move("thunder", "Thunder", "electric", "special", 110, 70, 10,
                    effect={"status": "paralyze", "chance": 30}),
    "thunder-punch": Move("thunder-punch", "Thunder Punch", "electric", "physical", 75, 100, 15),
    # --------- Grass ---------
    "vine-whip": Move("vine-whip", "Vine Whip", "grass", "physical", 45, 100, 25),
    "razor-leaf": Move("razor-leaf", "Razor Leaf", "grass", "physical", 55, 95, 25),
    "giga-drain": Move("giga-drain", "Giga Drain", "grass", "special", 75, 100, 10),
    "solar-beam": Move("solar-beam", "Solar Beam", "grass", "special", 120, 100, 10),
    "sleep-powder": Move("sleep-powder", "Sleep Powder", "grass", "status", 0, 75, 15,
                         effect={"status": "sleep", "chance": 100}),
    # --------- Ice ---------
    "ice-beam": Move("ice-beam", "Ice Beam", "ice", "special", 90, 100, 10,
                     effect={"status": "freeze", "chance": 10}),
    "blizzard": Move("blizzard", "Blizzard", "ice", "special", 110, 70, 5,
                     effect={"status": "freeze", "chance": 10}),
    "ice-punch": Move("ice-punch", "Ice Punch", "ice", "physical", 75, 100, 15),
    # --------- Fighting ---------
    "karate-chop": Move("karate-chop", "Karate Chop", "fighting", "physical", 50, 100, 25),
    "brick-break": Move("brick-break", "Brick Break", "fighting", "physical", 75, 100, 15),
    "close-combat": Move("close-combat", "Close Combat", "fighting", "physical", 120, 100, 5,
                         effect={"stat": "def", "stage": -1, "self": True}),
    # --------- Poison ---------
    "poison-sting": Move("poison-sting", "Poison Sting", "poison", "physical", 15, 100, 35),
    "sludge-bomb": Move("sludge-bomb", "Sludge Bomb", "poison", "special", 90, 100, 10,
                        effect={"status": "poison", "chance": 30}),
    "acid": Move("acid", "Acid", "poison", "special", 40, 100, 30),
    # --------- Ground ---------
    "earthquake": Move("earthquake", "Earthquake", "ground", "physical", 100, 100, 10),
    "dig": Move("dig", "Dig", "ground", "physical", 80, 100, 10),
    "mud-shot": Move("mud-shot", "Mud Shot", "ground", "special", 55, 95, 15),
    # --------- Flying ---------
    "wing-attack": Move("wing-attack", "Wing Attack", "flying", "physical", 60, 100, 35),
    "aerial-ace": Move("aerial-ace", "Aerial Ace", "flying", "physical", 60, 0, 20),
    "air-slash": Move("air-slash", "Air Slash", "flying", "special", 75, 95, 15),
    "peck": Move("peck", "Peck", "flying", "physical", 35, 100, 35),
    # --------- Psychic ---------
    "confusion": Move("confusion", "Confusion", "psychic", "special", 50, 100, 25),
    "psychic": Move("psychic", "Psychic", "psychic", "special", 90, 100, 10,
                    effect={"stat": "spd", "stage": -1, "self": False, "chance": 10}),
    "psybeam": Move("psybeam", "Psybeam", "psychic", "special", 65, 100, 20),
    # --------- Bug ---------
    "bug-bite": Move("bug-bite", "Bug Bite", "bug", "physical", 60, 100, 20),
    "x-scissor": Move("x-scissor", "X-Scissor", "bug", "physical", 80, 100, 15),
    # --------- Rock ---------
    "rock-throw": Move("rock-throw", "Rock Throw", "rock", "physical", 50, 90, 15),
    "rock-slide": Move("rock-slide", "Rock Slide", "rock", "physical", 75, 90, 10),
    # --------- Ghost ---------
    "shadow-ball": Move("shadow-ball", "Shadow Ball", "ghost", "special", 80, 100, 15,
                        effect={"stat": "spd", "stage": -1, "self": False, "chance": 20}),
    "lick": Move("lick", "Lick", "ghost", "physical", 30, 100, 30),
    # --------- Dragon ---------
    "dragon-claw": Move("dragon-claw", "Dragon Claw", "dragon", "physical", 80, 100, 15),
    "dragon-breath": Move("dragon-breath", "Dragon Breath", "dragon", "special", 60, 100, 20),
    # --------- Dark ---------
    "bite": Move("bite", "Bite", "dark", "physical", 60, 100, 25),
    "crunch": Move("crunch", "Crunch", "dark", "physical", 80, 100, 15),
    # --------- Steel ---------
    "metal-claw": Move("metal-claw", "Metal Claw", "steel", "physical", 50, 95, 35),
    "iron-tail": Move("iron-tail", "Iron Tail", "steel", "physical", 100, 75, 15),
    # --------- Fairy ---------
    "fairy-wind": Move("fairy-wind", "Fairy Wind", "fairy", "special", 40, 100, 30),
    "moonblast": Move("moonblast", "Moonblast", "fairy", "special", 95, 100, 15),
    "dazzling-gleam": Move("dazzling-gleam", "Dazzling Gleam", "fairy", "special", 80, 100, 10),
}

# Movimento de emergência (Struggle) caso uma espécie não tenha movepool.
DEFAULT_MOVE_BY_TYPE: dict[str, str] = {
    "normal": "tackle", "fire": "ember", "water": "water-gun", "electric": "thunder-shock",
    "grass": "vine-whip", "ice": "ice-beam", "fighting": "karate-chop", "poison": "acid",
    "ground": "mud-shot", "flying": "peck", "psychic": "confusion", "bug": "bug-bite",
    "rock": "rock-throw", "ghost": "lick", "dragon": "dragon-breath", "dark": "bite",
    "steel": "metal-claw", "fairy": "fairy-wind",
}


def get_move(key: str) -> Move | None:
    return MOVES.get(key)


def default_moveset(types: list[str]) -> list[str]:
    """Gera um conjunto de 4 golpes coerente com os tipos da espécie."""
    moves: list[str] = ["tackle"]
    for t in types:
        m = DEFAULT_MOVE_BY_TYPE.get(t)
        if m and m not in moves:
            moves.append(m)
    # completa até 4 com golpes do primeiro tipo
    primary = types[0] if types else "normal"
    pool = [k for k, mv in MOVES.items()
            if mv.type == primary and mv.category != "status" and k not in moves]
    for k in pool:
        if len(moves) >= 4:
            break
        moves.append(k)
    while len(moves) < 4:
        moves.append("tackle")
    return moves[:4]
