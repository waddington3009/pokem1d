"""Tabela de raridade, seleção ponderada de spawn e roll de shiny."""
from __future__ import annotations

import random

from bot.data.pokemon_data import POKEDEX, Species

# Peso relativo de cada tier (quanto maior, mais comum no spawn).
# Peso POR ESPÉCIE. A chance final de cada tier depende de quantas espécies ele
# tem (super=8, lendário=35, mítico=13), por isso os tiers raros levam peso alto.
# Calibrado para: Super Raro 5% • Lendário 1.5% • Mítico 0.2% no explore.
RARITY_WEIGHTS: dict[str, float] = {
    "common": 100.0,
    "uncommon": 45.0,
    "rare": 12.0,
    "superrare": 254.22,   # 5.0%   (~1 em 20)
    "legendary": 17.432,   # 1.5%   (~1 em 67)
    "mythical": 6.258,     # 0.2%   (~1 em 500)
}

RARITY_LABEL: dict[str, str] = {
    "common": "Comum",
    "uncommon": "Incomum",
    "rare": "Raro",
    "superrare": "Super Raro",
    "legendary": "Lendário",
    "mythical": "Mítico",
}

RARITY_EMOJI: dict[str, str] = {
    "common": "⚪",
    "uncommon": "🟢",
    "rare": "🔵",
    "superrare": "🟣",
    "legendary": "🟠",
    "mythical": "🌈",
}

RARITY_COLOR: dict[str, int] = {
    "common": 0xB0B0B0,
    "uncommon": 0x57F287,
    "rare": 0x5865F2,
    "superrare": 0x9B59B6,
    "legendary": 0xE67E22,
    "mythical": 0xE91E63,
}


def rarity_label(rarity: str) -> str:
    return RARITY_LABEL.get(rarity, rarity.title())


def pick_spawn_species() -> Species:
    """Escolhe uma espécie para spawnar, ponderada pela raridade."""
    species = POKEDEX.all()
    weights = [RARITY_WEIGHTS.get(s.rarity, 1.0) for s in species]
    return random.choices(species, weights=weights, k=1)[0]


def roll_shiny(denominator: int, bonus: float = 1.0) -> bool:
    """True se for shiny. Chance = bonus / denominator."""
    if denominator <= 0:
        return False
    # quanto maior o bônus, maior a chance: comparamos contra denom/bonus
    threshold = max(1, int(denominator / max(bonus, 0.0001)))
    return random.randint(1, threshold) == 1


def catch_coin_reward(species: Species, shiny: bool, lo: int, hi: int) -> int:
    """Recompensa em moedas por capturar, escalando com a raridade."""
    mult = {
        "common": 1.0, "uncommon": 1.4, "rare": 2.2,
        "superrare": 3.5, "legendary": 8.0, "mythical": 15.0,
    }.get(species.rarity, 1.0)
    base = random.randint(lo, hi)
    coins = int(base * mult)
    if shiny:
        coins *= 5
    return coins
