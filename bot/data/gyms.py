"""Definição da Liga: 8 ginásios (por tipo) + Elite dos 4 + Campeão.

Cada desafio é PvE: o jogador enfrenta o time do Líder (controlado pela IA),
em ordem. Vencer dá uma insígnia + moedas + um item (na 1ª vez).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Challenge:
    key: str                       # gym1..gym8, elite1..elite4, champion
    name: str                      # nome do desafio
    leader: str                    # nome do líder
    kind: str                      # "gym" | "elite" | "champion"
    badge: str                     # nome da insígnia
    emoji: str                     # emoji da insígnia
    team: list[tuple[str, int]]    # [(espécie, nível), ...]
    reward_coins: int
    reward_item: str | None = None
    reward_item_qty: int = 1
    perfect: bool = False          # líder com IVs perfeitos (31) — desafios endgame


CHALLENGES: list[Challenge] = [
    # ---------------- 8 GINÁSIOS (por tipo) ----------------
    Challenge("gym1", "Ginásio de Pedra", "Líder Rocha", "gym", "Insígnia Rocha", "🪨",
              [("Geodude", 11), ("Graveler", 12), ("Onix", 14)], 600, "greatball", 3),
    Challenge("gym2", "Ginásio de Água", "Líder Maré", "gym", "Insígnia Cascata", "💧",
              [("Staryu", 17), ("Wartortle", 18), ("Starmie", 20)], 900, "rare-candy", 2),
    Challenge("gym3", "Ginásio Elétrico", "Líder Tesla", "gym", "Insígnia Trovão", "⚡",
              [("Pikachu", 23), ("Magneton", 24), ("Raichu", 26)], 1300, "ultraball", 2),
    Challenge("gym4", "Ginásio de Planta", "Líder Flora", "gym", "Insígnia Folha", "🍃",
              [("Gloom", 29), ("Victreebel", 30), ("Venusaur", 32)], 1700, "leaf-stone", 1),
    Challenge("gym5", "Ginásio de Fogo", "Líder Brasa", "gym", "Insígnia Chama", "🔥",
              [("Growlithe", 35), ("Magmar", 36), ("Arcanine", 38)], 2200, "rare-candy", 3),
    Challenge("gym6", "Ginásio Psíquico", "Líder Mente", "gym", "Insígnia Pântano", "🔮",
              [("Kadabra", 41), ("Hypno", 42), ("Alakazam", 44)], 2700, "ultraball", 3),
    Challenge("gym7", "Ginásio Fantasma", "Líder Sombra", "gym", "Insígnia Alma", "👻",
              [("Haunter", 46), ("Misdreavus", 47), ("Mismagius", 48), ("Gengar", 50)], 3300, "dusk-stone", 1),
    Challenge("gym8", "Ginásio Dragão", "Líder Drago", "gym", "Insígnia Dragão", "🐉",
              [("Dragonair", 53), ("Gabite", 54), ("Dragonite", 56), ("Garchomp", 58)], 4200, "masterball", 1),

    # ---------------- ELITE DOS 4 ----------------
    Challenge("elite1", "Elite — Sombrio", "Elite Noir", "elite", "Selo Sombrio", "🌑",
              [("Houndoom", 61), ("Honchkrow", 62), ("Tyranitar", 63), ("Hydreigon", 64)], 6000, "ultraball", 5),
    Challenge("elite2", "Elite — Aço", "Elite Ferra", "elite", "Selo de Aço", "⚙️",
              [("Steelix", 63), ("Aggron", 64), ("Metagross", 65), ("Bisharp", 66)], 7000, "rare-candy", 5),
    Challenge("elite3", "Elite — Lutador", "Elite Punho", "elite", "Selo do Punho", "🥊",
              [("Machamp", 65), ("Hariyama", 66), ("Conkeldurr", 67), ("Lucario", 68)], 8000, "masterball", 1),
    Challenge("elite4", "Elite — Gelo", "Elite Gélida", "elite", "Selo Glacial", "❄️",
              [("Lapras", 67), ("Glalie", 68), ("Weavile", 69), ("Mamoswine", 70)], 9000, "masterball", 1),

    # ---------------- CAMPEÃO ----------------
    Challenge("champion", "CAMPEÃO da Liga", "Campeão Lendário", "champion", "Troféu de Campeão", "👑",
              [("Arcanine", 73), ("Gengar", 74), ("Tyranitar", 74),
               ("Metagross", 75), ("Garchomp", 76), ("Dragonite", 77)], 25000, "iv-crystal", 1),

    # ---------------- ENDGAME: COVIS LENDÁRIOS + CÂMARA DOS MÍTICOS ----------------
    Challenge("lair1", "Covil Lendário I", "Guardião dos Céus", "legend", "Selo Alado", "🦅",
              [("Articuno", 80), ("Zapdos", 80), ("Moltres", 82)], 35000, "masterball", 2),
    Challenge("lair2", "Covil Lendário II", "Senhor das Eras", "legend", "Selo Temporal", "⏳",
              [("Dialga", 84), ("Palkia", 85), ("Giratina", 86)], 50000, "iv-crystal", 1),
    Challenge("lair3", "Trono dos Titãs", "Soberano Primordial", "legend", "Selo Divino", "🌠",
              [("Kyogre", 88), ("Groudon", 88), ("Lugia", 89), ("Rayquaza", 90), ("Mewtwo", 90)],
              80000, "masterball", 3),
    Challenge("myth", "A CÂMARA DOS MÍTICOS", "Entidade Mítica", "myth", "Coroa Mítica", "💠",
              [("Mew", 100), ("Celebi", 100), ("Jirachi", 100),
               ("Darkrai", 100), ("Genesect", 100), ("Arceus", 100)],
              250000, "iv-crystal", 3, perfect=True),
]

CHALLENGES_BY_KEY = {c.key: c for c in CHALLENGES}
GYM_KEYS = [c.key for c in CHALLENGES if c.kind == "gym"]


def challenge_index(key: str) -> int:
    for i, c in enumerate(CHALLENGES):
        if c.key == key:
            return i
    return -1


def party_slots(badges: list) -> int:
    """Slots de time = 3 + (insígnias de ginásio // 2), até 6."""
    gym = sum(1 for b in (badges or []) if str(b).startswith("gym"))
    return min(6, 3 + gym // 2)


def resolve_challenge(query: str) -> Challenge | None:
    """Resolve por número (1-13), key (gym1) ou nome do tipo/desafio."""
    q = query.lower().strip()
    if q.isdigit():
        i = int(q) - 1
        if 0 <= i < len(CHALLENGES):
            return CHALLENGES[i]
        return None
    if q in CHALLENGES_BY_KEY:
        return CHALLENGES_BY_KEY[q]
    # por palavra no nome do desafio/líder/tipo
    for c in CHALLENGES:
        if q in c.name.lower() or q in c.leader.lower():
            return c
    return None
