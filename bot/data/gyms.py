"""Definição da Liga: 8 ginásios (por tipo) + Elite dos 4 + Campeão + endgame.

Cada desafio é PvE: o jogador enfrenta o time do Líder (controlado pela IA), em
ordem. Vencer dá uma insígnia + moedas + um item (na 1ª vez).

REFORMULAÇÃO (Liga Suprema): a liga ativa foi refeita e ficou MUITO mais difícil —
times cheios, níveis altos, **IVs perfeitos** em todos os líderes e vários aces que
**Mega Evoluem** no meio da batalha. As insígnias antigas continuam válidas para quem
já as tem (`LEGACY_CHALLENGES`), mas a progressão agora é pela Liga Suprema (chaves
`s2_*`), com insígnias novas.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Challenge:
    key: str                       # s2_gym1..s2_gym8, s2_elite1..s2_elite4, s2_champion...
    name: str                      # nome do desafio
    leader: str                    # nome do líder
    kind: str                      # "gym" | "elite" | "champion" | "legend" | "myth"
    badge: str                     # nome da insígnia
    emoji: str                     # emoji da insígnia
    # time do líder: (espécie, nível) ou (espécie, nível, mega_stone_key) p/ Mega Evoluir
    team: list[tuple]
    reward_coins: int
    reward_item: str | None = None
    reward_item_qty: int = 1
    perfect: bool = False          # líder com IVs perfeitos (31)


# ==========================================================================
#  LIGA SUPREMA (ativa) — refeita, ~3x mais difícil. Todos com IV perfeito.
# ==========================================================================
CHALLENGES: list[Challenge] = [
    # ---------------- 8 GINÁSIOS (por tipo) ----------------
    Challenge("s2_gym1", "Ginásio Rocha (Supremo)", "Líder Granito", "gym",
              "Insígnia Granito", "🪨",
              [("Golem", 40), ("Rhyperior", 41), ("Aerodactyl", 42),
               ("Gigalith", 43), ("Tyranitar", 45)],
              8000, "greatball", 5, perfect=True),
    Challenge("s2_gym2", "Ginásio Água (Supremo)", "Líder Abissal", "gym",
              "Insígnia Abissal", "💧",
              [("Starmie", 47), ("Gyarados", 47), ("Kingdra", 48),
               ("Milotic", 49), ("Swampert", 51)],
              12000, "ultraball", 3, perfect=True),
    Challenge("s2_gym3", "Ginásio Elétrico (Supremo)", "Líder Tempestade", "gym",
              "Insígnia Tempestade", "⚡",
              [("Jolteon", 53), ("Electivire", 54), ("Magnezone", 54),
               ("Ampharos", 55), ("Manectric", 57)],
              16000, "rare-candy", 5, perfect=True),
    Challenge("s2_gym4", "Ginásio Planta (Supremo)", "Líder Selva", "gym",
              "Insígnia Selva", "🍃",
              [("Roserade", 59), ("Breloom", 60), ("Ferrothorn", 61),
               ("Venusaur", 62), ("Sceptile", 63)],
              20000, "ultraball", 5, perfect=True),
    Challenge("s2_gym5", "Ginásio Fogo (Supremo)", "Líder Inferno", "gym",
              "Insígnia Inferno", "🔥",
              [("Arcanine", 65), ("Magmortar", 65), ("Houndoom", 66),
               ("Chandelure", 67), ("Blaziken", 69)],
              25000, "hyper-potion", 5, perfect=True),
    Challenge("s2_gym6", "Ginásio Psíquico (Supremo)", "Líder Miragem", "gym",
              "Insígnia Miragem", "🔮",
              [("Espeon", 71), ("Alakazam", 71), ("Gardevoir", 72),
               ("Metagross", 73), ("Gallade", 75)],
              30000, "max-potion", 3, perfect=True),
    Challenge("s2_gym7", "Ginásio Fantasma (Supremo)", "Líder Espectral", "gym",
              "Insígnia Espectral", "👻",
              [("Mismagius", 77), ("Cofagrigus", 78), ("Dusknoir", 79),
               ("Chandelure", 80), ("Gengar", 82, "gengarite")],
              38000, "gengarite", 1, perfect=True),
    Challenge("s2_gym8", "Ginásio Dragão (Supremo)", "Líder Dracônico", "gym",
              "Insígnia Dracônica", "🐉",
              [("Flygon", 84), ("Haxorus", 85), ("Dragonite", 86),
               ("Hydreigon", 87), ("Salamence", 88), ("Garchomp", 90, "garchompite")],
              50000, "garchompite", 1, perfect=True),

    # ---------------- ELITE DOS 4 ----------------
    Challenge("s2_elite1", "Elite Suprema — Sombrio", "Elite Umbra", "elite",
              "Selo da Escuridão", "🌑",
              [("Weavile", 88), ("Bisharp", 89), ("Krookodile", 90),
               ("Hydreigon", 91), ("Houndoom", 92), ("Tyranitar", 94, "tyranitarite")],
              65000, "houndoominite", 1, perfect=True),
    Challenge("s2_elite2", "Elite Suprema — Aço", "Elite Ferrus", "elite",
              "Selo Metálico", "⚙️",
              [("Bronzong", 89), ("Excadrill", 90), ("Steelix", 91),
               ("Aggron", 92), ("Scizor", 93), ("Metagross", 94, "metagrossite")],
              75000, "metagrossite", 1, perfect=True),
    Challenge("s2_elite3", "Elite Suprema — Lutador", "Elite Pugna", "elite",
              "Selo do Punho", "🥊",
              [("Machamp", 90), ("Conkeldurr", 91), ("Hariyama", 91),
               ("Infernape", 92), ("Mienshao", 93), ("Lucario", 94, "lucarionite")],
              85000, "lucarionite", 1, perfect=True),
    Challenge("s2_elite4", "Elite Suprema — Dragão", "Elite Draconis", "elite",
              "Selo Celestial", "🐲",
              [("Kingdra", 91), ("Flygon", 92), ("Dragonite", 93),
               ("Hydreigon", 93), ("Salamence", 94), ("Garchomp", 95, "garchompite")],
              95000, "full-restore", 5, perfect=True),

    # ---------------- CAMPEÃO ----------------
    Challenge("s2_champion", "CAMPEÃO da Liga Suprema", "Campeã Absoluta", "champion",
              "Coroa da Liga Suprema", "👑",
              [("Gengar", 98), ("Tyranitar", 98), ("Metagross", 99),
               ("Dragonite", 99), ("Garchomp", 100), ("Salamence", 100, "salamencite")],
              150000, "salamencite", 1, perfect=True),

    # ---------------- ENDGAME: COVIS LENDÁRIOS + CÂMARA DOS MÍTICOS ----------------
    Challenge("s2_lair1", "Covil dos Ventos", "Guardião Alado", "legend",
              "Selo Tempestuoso", "🦅",
              [("Articuno", 100), ("Zapdos", 100), ("Moltres", 100),
               ("Dragonite", 100), ("Salamence", 100, "salamencite")],
              120000, "masterball", 3, perfect=True),
    Challenge("s2_lair2", "Covil Temporal", "Soberano das Eras", "legend",
              "Selo do Tempo", "⏳",
              [("Dialga", 100), ("Palkia", 100), ("Giratina", 100),
               ("Garchomp", 100), ("Latios", 100, "latiosite")],
              180000, "latiosite", 1, perfect=True),
    Challenge("s2_lair3", "Trono Primordial", "Titã Soberano", "legend",
              "Selo Soberano", "🌠",
              [("Lugia", 100), ("Ho-Oh", 100), ("Groudon", 100, "red-orb"),
               ("Kyogre", 100, "blue-orb"), ("Rayquaza", 100, "meteorite-z"),
               ("Mewtwo", 100, "mewtwonite-y")],
              250000, "iv-crystal", 2, perfect=True),
    Challenge("s2_myth", "A CÂMARA SUPREMA DOS MÍTICOS", "Entidade Suprema", "myth",
              "Coroa Mítica Absoluta", "💠",
              [("Mew", 100), ("Celebi", 100), ("Jirachi", 100),
               ("Darkrai", 100), ("Genesect", 100), ("Arceus", 100)],
              500000, "iv-crystal", 5, perfect=True),
]


# ==========================================================================
#  LIGA ANTIGA (legado) — só para EXIBIR as insígnias de quem já as tem.
#  Não é mais desafiável; as chaves antigas continuam válidas no perfil.
# ==========================================================================
LEGACY_CHALLENGES: list[Challenge] = [
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
    Challenge("elite1", "Elite — Sombrio", "Elite Noir", "elite", "Selo Sombrio", "🌑",
              [("Houndoom", 61), ("Honchkrow", 62), ("Tyranitar", 63), ("Hydreigon", 64)], 6000, "ultraball", 5),
    Challenge("elite2", "Elite — Aço", "Elite Ferra", "elite", "Selo de Aço", "⚙️",
              [("Steelix", 63), ("Aggron", 64), ("Metagross", 65), ("Bisharp", 66)], 7000, "rare-candy", 5),
    Challenge("elite3", "Elite — Lutador", "Elite Punho", "elite", "Selo do Punho", "🥊",
              [("Machamp", 65), ("Hariyama", 66), ("Conkeldurr", 67), ("Lucario", 68)], 8000, "masterball", 1),
    Challenge("elite4", "Elite — Gelo", "Elite Gélida", "elite", "Selo Glacial", "❄️",
              [("Lapras", 67), ("Glalie", 68), ("Weavile", 69), ("Mamoswine", 70)], 9000, "masterball", 1),
    Challenge("champion", "CAMPEÃO da Liga", "Campeão Lendário", "champion", "Troféu de Campeão", "👑",
              [("Arcanine", 73), ("Gengar", 74), ("Tyranitar", 74),
               ("Metagross", 75), ("Garchomp", 76), ("Dragonite", 77)], 25000, "iv-crystal", 1),
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

# Mapa por chave: inclui a liga ativa E a antiga (p/ exibir insígnias já conquistadas).
ACTIVE_BY_KEY = {c.key: c for c in CHALLENGES}
CHALLENGES_BY_KEY = {**{c.key: c for c in LEGACY_CHALLENGES}, **ACTIVE_BY_KEY}
GYM_KEYS = [c.key for c in CHALLENGES if c.kind == "gym"]


def leader_mons(ch: Challenge):
    """Itera o time do líder como (nome, nível, mega_stone|None), aceitando 2- ou 3-tuplas."""
    for entry in ch.team:
        if len(entry) >= 3:
            yield entry[0], entry[1], entry[2]
        else:
            yield entry[0], entry[1], None


def challenge_index(key: str) -> int:
    for i, c in enumerate(CHALLENGES):
        if c.key == key:
            return i
    return -1


def party_slots(badges: list) -> int:
    """Slots de time = 3 + (insígnias de ginásio // 2), até 6.

    Conta ginásios da liga ativa E da antiga — quem já zerou a liga antiga mantém
    os slots que já tinha.
    """
    gym = 0
    for b in (badges or []):
        c = CHALLENGES_BY_KEY.get(str(b))
        if c is not None and c.kind == "gym":
            gym += 1
    return min(6, 3 + gym // 2)


def resolve_challenge(query: str) -> Challenge | None:
    """Resolve por número (1..N da liga ativa), key (s2_gym1) ou nome do tipo/desafio."""
    q = query.lower().strip()
    if q.isdigit():
        i = int(q) - 1
        if 0 <= i < len(CHALLENGES):
            return CHALLENGES[i]
        return None
    if q in ACTIVE_BY_KEY:
        return ACTIVE_BY_KEY[q]
    # por palavra no nome do desafio/líder
    for c in CHALLENGES:
        if q in c.name.lower() or q in c.leader.lower():
            return c
    return None
