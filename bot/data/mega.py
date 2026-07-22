"""Formas Mega (e Primal) — dados usados só em batalha.

Uma Mega existe apenas durante a luta: ao segurar a Mega Stone certa, o pokémon
ativo pode Mega Evoluir (1x por batalha), trocando tipos/atributos/sprite; ao fim
da batalha volta ao normal (nada é salvo no banco).

Cada entrada é indexada pela `stone_key` (a chave do item Mega Stone). O sprite usa
o `mega_id` (id de forma do PokéAPI). `base_id` liga a pedra à espécie de origem.
"""
from __future__ import annotations

from dataclasses import dataclass


def _s(hp: int, atk: int, df: int, spa: int, spd: int, spe: int) -> dict[str, int]:
    return {"hp": hp, "atk": atk, "def": df, "spa": spa, "spd": spd, "spe": spe}


@dataclass(frozen=True)
class MegaForm:
    stone_key: str
    stone_name: str
    emoji: str
    base_id: int
    base_name: str
    mega_id: int                 # id de sprite (forma do PokéAPI)
    mega_name: str
    types: tuple[str, ...]
    base_stats: dict             # hp/atk/def/spa/spd/spe


# Lista canônica de Megas/Primais (base_id <= 651: presentes no dataset do bot).
_FORMS: list[MegaForm] = [
    MegaForm("venusaurite", "Venusaurite", "🌿", 3, "Venusaur", 10033, "Mega Venusaur",
             ("grass", "poison"), _s(80, 100, 123, 122, 120, 80)),
    MegaForm("charizardite-x", "Charizardite X", "🔥", 6, "Charizard", 10034, "Mega Charizard X",
             ("fire", "dragon"), _s(78, 130, 111, 130, 85, 100)),
    MegaForm("charizardite-y", "Charizardite Y", "☄️", 6, "Charizard", 10035, "Mega Charizard Y",
             ("fire", "flying"), _s(78, 104, 78, 159, 115, 100)),
    MegaForm("blastoisinite", "Blastoisinite", "💧", 9, "Blastoise", 10036, "Mega Blastoise",
             ("water",), _s(79, 103, 120, 135, 115, 78)),
    MegaForm("beedrillite", "Beedrillite", "🐝", 15, "Beedrill", 10090, "Mega Beedrill",
             ("bug", "poison"), _s(65, 150, 40, 15, 80, 145)),
    MegaForm("pidgeotite", "Pidgeotite", "🕊️", 18, "Pidgeot", 10073, "Mega Pidgeot",
             ("normal", "flying"), _s(83, 80, 80, 135, 80, 121)),
    MegaForm("alakazite", "Alakazite", "🥄", 65, "Alakazam", 10037, "Mega Alakazam",
             ("psychic",), _s(55, 50, 65, 175, 105, 150)),
    MegaForm("slowbronite", "Slowbronite", "🐚", 80, "Slowbro", 10071, "Mega Slowbro",
             ("water", "psychic"), _s(95, 75, 180, 130, 80, 30)),
    MegaForm("gengarite", "Gengarite", "👻", 94, "Gengar", 10038, "Mega Gengar",
             ("ghost", "poison"), _s(60, 65, 80, 170, 95, 130)),
    MegaForm("kangaskhanite", "Kangaskhanite", "🦘", 115, "Kangaskhan", 10039, "Mega Kangaskhan",
             ("normal",), _s(105, 125, 100, 60, 100, 100)),
    MegaForm("pinsirite", "Pinsirite", "🪲", 127, "Pinsir", 10040, "Mega Pinsir",
             ("bug", "flying"), _s(65, 155, 120, 65, 90, 105)),
    MegaForm("gyaradosite", "Gyaradosite", "🌊", 130, "Gyarados", 10041, "Mega Gyarados",
             ("water", "dark"), _s(95, 155, 109, 70, 130, 81)),
    MegaForm("aerodactylite", "Aerodactylite", "🦴", 142, "Aerodactyl", 10042, "Mega Aerodactyl",
             ("rock", "flying"), _s(80, 135, 85, 70, 95, 150)),
    MegaForm("mewtwonite-x", "Mewtwonite X", "🧬", 150, "Mewtwo", 10043, "Mega Mewtwo X",
             ("psychic", "fighting"), _s(106, 190, 100, 154, 100, 130)),
    MegaForm("mewtwonite-y", "Mewtwonite Y", "🔮", 150, "Mewtwo", 10044, "Mega Mewtwo Y",
             ("psychic",), _s(106, 150, 70, 194, 120, 140)),
    MegaForm("ampharosite", "Ampharosite", "⚡", 181, "Ampharos", 10045, "Mega Ampharos",
             ("electric", "dragon"), _s(90, 95, 105, 165, 110, 45)),
    MegaForm("steelixite", "Steelixite", "⛓️", 208, "Steelix", 10072, "Mega Steelix",
             ("steel", "ground"), _s(75, 125, 230, 55, 95, 30)),
    MegaForm("scizorite", "Scizorite", "✂️", 212, "Scizor", 10046, "Mega Scizor",
             ("bug", "steel"), _s(70, 150, 140, 65, 100, 75)),
    MegaForm("heracronite", "Heracronite", "🦌", 214, "Heracross", 10047, "Mega Heracross",
             ("bug", "fighting"), _s(80, 185, 115, 40, 105, 75)),
    MegaForm("houndoominite", "Houndoominite", "🐺", 229, "Houndoom", 10048, "Mega Houndoom",
             ("dark", "fire"), _s(75, 90, 90, 140, 90, 115)),
    MegaForm("tyranitarite", "Tyranitarite", "🦖", 248, "Tyranitar", 10049, "Mega Tyranitar",
             ("rock", "dark"), _s(100, 164, 150, 95, 120, 71)),
    MegaForm("sceptilite", "Sceptilite", "🦎", 254, "Sceptile", 10065, "Mega Sceptile",
             ("grass", "dragon"), _s(70, 110, 75, 145, 85, 145)),
    MegaForm("blazikenite", "Blazikenite", "🥊", 257, "Blaziken", 10050, "Mega Blaziken",
             ("fire", "fighting"), _s(80, 160, 80, 130, 80, 100)),
    MegaForm("swampertite", "Swampertite", "🌀", 260, "Swampert", 10064, "Mega Swampert",
             ("water", "ground"), _s(100, 150, 110, 95, 110, 70)),
    MegaForm("gardevoirite", "Gardevoirite", "💃", 282, "Gardevoir", 10051, "Mega Gardevoir",
             ("psychic", "fairy"), _s(68, 85, 65, 165, 135, 100)),
    MegaForm("sablenite", "Sablenite", "💎", 302, "Sableye", 10066, "Mega Sableye",
             ("dark", "ghost"), _s(50, 85, 125, 85, 115, 20)),
    MegaForm("mawilite", "Mawilite", "👄", 303, "Mawile", 10052, "Mega Mawile",
             ("steel", "fairy"), _s(50, 105, 125, 55, 95, 50)),
    MegaForm("aggronite", "Aggronite", "🛡️", 306, "Aggron", 10053, "Mega Aggron",
             ("steel",), _s(70, 140, 230, 60, 80, 50)),
    MegaForm("medichamite", "Medichamite", "🧘", 308, "Medicham", 10054, "Mega Medicham",
             ("fighting", "psychic"), _s(60, 100, 85, 80, 85, 100)),
    MegaForm("manectite", "Manectite", "🐕", 310, "Manectric", 10055, "Mega Manectric",
             ("electric",), _s(70, 75, 80, 135, 80, 135)),
    MegaForm("sharpedonite", "Sharpedonite", "🦈", 319, "Sharpedo", 10070, "Mega Sharpedo",
             ("water", "dark"), _s(70, 140, 70, 110, 65, 105)),
    MegaForm("cameruptite", "Cameruptite", "🌋", 323, "Camerupt", 10087, "Mega Camerupt",
             ("fire", "ground"), _s(70, 120, 100, 145, 105, 20)),
    MegaForm("altarianite", "Altarianite", "☁️", 334, "Altaria", 10067, "Mega Altaria",
             ("dragon", "fairy"), _s(75, 110, 110, 110, 105, 80)),
    MegaForm("banettite", "Banettite", "🎎", 354, "Banette", 10056, "Mega Banette",
             ("ghost",), _s(64, 165, 75, 93, 83, 75)),
    MegaForm("absolite", "Absolite", "🌙", 359, "Absol", 10057, "Mega Absol",
             ("dark",), _s(65, 150, 60, 115, 60, 115)),
    MegaForm("glalitite", "Glalitite", "❄️", 362, "Glalie", 10074, "Mega Glalie",
             ("ice",), _s(80, 120, 80, 120, 80, 100)),
    MegaForm("salamencite", "Salamencite", "🐲", 373, "Salamence", 10089, "Mega Salamence",
             ("dragon", "flying"), _s(95, 145, 130, 120, 90, 120)),
    MegaForm("metagrossite", "Metagrossite", "🤖", 376, "Metagross", 10076, "Mega Metagross",
             ("steel", "psychic"), _s(80, 145, 150, 105, 110, 110)),
    MegaForm("latiasite", "Latiasite", "🔴", 380, "Latias", 10062, "Mega Latias",
             ("dragon", "psychic"), _s(80, 100, 120, 140, 150, 110)),
    MegaForm("latiosite", "Latiosite", "🔵", 381, "Latios", 10063, "Mega Latios",
             ("dragon", "psychic"), _s(80, 130, 100, 160, 120, 110)),
    MegaForm("blue-orb", "Orbe Azul", "🔷", 382, "Kyogre", 10077, "Primal Kyogre",
             ("water",), _s(100, 150, 90, 180, 160, 90)),
    MegaForm("red-orb", "Orbe Vermelho", "🔶", 383, "Groudon", 10078, "Primal Groudon",
             ("ground", "fire"), _s(100, 180, 160, 150, 90, 90)),
    MegaForm("meteorite-z", "Meteorito", "🌠", 384, "Rayquaza", 10079, "Mega Rayquaza",
             ("dragon", "flying"), _s(105, 180, 100, 180, 100, 115)),
    MegaForm("lopunnite", "Lopunnite", "🐇", 428, "Lopunny", 10088, "Mega Lopunny",
             ("normal", "fighting"), _s(65, 136, 94, 54, 96, 135)),
    MegaForm("garchompite", "Garchompite", "🦈", 445, "Garchomp", 10058, "Mega Garchomp",
             ("dragon", "ground"), _s(108, 170, 115, 120, 95, 92)),
    MegaForm("lucarionite", "Lucarionite", "🐾", 448, "Lucario", 10059, "Mega Lucario",
             ("fighting", "steel"), _s(70, 145, 88, 140, 70, 112)),
    MegaForm("abomasite", "Abomasite", "🌲", 460, "Abomasnow", 10060, "Mega Abomasnow",
             ("grass", "ice"), _s(90, 132, 105, 132, 105, 30)),
    MegaForm("galladite", "Galladite", "⚔️", 475, "Gallade", 10068, "Mega Gallade",
             ("psychic", "fighting"), _s(68, 165, 95, 65, 115, 110)),
    MegaForm("audinite", "Audinite", "🩺", 531, "Audino", 10069, "Mega Audino",
             ("normal", "fairy"), _s(103, 60, 126, 80, 126, 50)),
]

MEGA_FORMS: dict[str, MegaForm] = {f.stone_key: f for f in _FORMS}

# base_id -> lista de formas (algumas espécies têm X/Y)
MEGA_BY_BASE: dict[int, list[MegaForm]] = {}
for _f in _FORMS:
    MEGA_BY_BASE.setdefault(_f.base_id, []).append(_f)


def mega_for_stone(stone_key: str) -> MegaForm | None:
    return MEGA_FORMS.get(stone_key)


def megas_for_species(species_id: int) -> list[MegaForm]:
    return MEGA_BY_BASE.get(species_id, [])
