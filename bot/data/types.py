"""Tabela de tipos (efetividade) e cores associadas."""
from __future__ import annotations

# Multiplicadores: ataque do tipo (linha) contra defensor do tipo (coluna).
# Apenas relações != 1.0 são listadas; o resto é 1.0.
_CHART: dict[str, dict[str, float]] = {
    "normal":   {"rock": 0.5, "ghost": 0.0, "steel": 0.5},
    "fire":     {"fire": 0.5, "water": 0.5, "grass": 2.0, "ice": 2.0, "bug": 2.0,
                 "rock": 0.5, "dragon": 0.5, "steel": 2.0},
    "water":    {"fire": 2.0, "water": 0.5, "grass": 0.5, "ground": 2.0,
                 "rock": 2.0, "dragon": 0.5},
    "electric": {"water": 2.0, "electric": 0.5, "grass": 0.5, "ground": 0.0,
                 "flying": 2.0, "dragon": 0.5},
    "grass":    {"fire": 0.5, "water": 2.0, "grass": 0.5, "poison": 0.5,
                 "ground": 2.0, "flying": 0.5, "bug": 0.5, "rock": 2.0,
                 "dragon": 0.5, "steel": 0.5},
    "ice":      {"fire": 0.5, "water": 0.5, "grass": 2.0, "ice": 0.5,
                 "ground": 2.0, "flying": 2.0, "dragon": 2.0, "steel": 0.5},
    "fighting": {"normal": 2.0, "ice": 2.0, "poison": 0.5, "flying": 0.5,
                 "psychic": 0.5, "bug": 0.5, "rock": 2.0, "ghost": 0.0,
                 "dark": 2.0, "steel": 2.0, "fairy": 0.5},
    "poison":   {"grass": 2.0, "poison": 0.5, "ground": 0.5, "rock": 0.5,
                 "ghost": 0.5, "steel": 0.0, "fairy": 2.0},
    "ground":   {"fire": 2.0, "electric": 2.0, "grass": 0.5, "poison": 2.0,
                 "flying": 0.0, "bug": 0.5, "rock": 2.0, "steel": 2.0},
    "flying":   {"electric": 0.5, "grass": 2.0, "fighting": 2.0, "bug": 2.0,
                 "rock": 0.5, "steel": 0.5},
    "psychic":  {"fighting": 2.0, "poison": 2.0, "psychic": 0.5, "dark": 0.0,
                 "steel": 0.5},
    "bug":      {"fire": 0.5, "grass": 2.0, "fighting": 0.5, "poison": 0.5,
                 "flying": 0.5, "psychic": 2.0, "ghost": 0.5, "dark": 2.0,
                 "steel": 0.5, "fairy": 0.5},
    "rock":     {"fire": 2.0, "ice": 2.0, "fighting": 0.5, "ground": 0.5,
                 "flying": 2.0, "bug": 2.0, "steel": 0.5},
    "ghost":    {"normal": 0.0, "psychic": 2.0, "ghost": 2.0, "dark": 0.5},
    "dragon":   {"dragon": 2.0, "steel": 0.5, "fairy": 0.0},
    "dark":     {"fighting": 0.5, "psychic": 2.0, "ghost": 2.0, "dark": 0.5,
                 "fairy": 0.5},
    "steel":    {"fire": 0.5, "water": 0.5, "electric": 0.5, "ice": 2.0,
                 "rock": 2.0, "steel": 0.5, "fairy": 2.0},
    "fairy":    {"fire": 0.5, "fighting": 2.0, "poison": 0.5, "dragon": 2.0,
                 "dark": 2.0, "steel": 0.5},
}

TYPE_COLORS: dict[str, int] = {
    "normal": 0xA8A77A, "fire": 0xEE8130, "water": 0x6390F0, "electric": 0xF7D02C,
    "grass": 0x7AC74C, "ice": 0x96D9D6, "fighting": 0xC22E28, "poison": 0xA33EA1,
    "ground": 0xE2BF65, "flying": 0xA98FF3, "psychic": 0xF95587, "bug": 0xA6B91A,
    "rock": 0xB6A136, "ghost": 0x735797, "dragon": 0x6F35FC, "dark": 0x705746,
    "steel": 0xB7B7CE, "fairy": 0xD685AD,
}

TYPE_EMOJI: dict[str, str] = {
    "normal": "⚪", "fire": "🔥", "water": "💧", "electric": "⚡", "grass": "🍃",
    "ice": "❄️", "fighting": "🥊", "poison": "☠️", "ground": "⛰️", "flying": "🕊️",
    "psychic": "🔮", "bug": "🐛", "rock": "🪨", "ghost": "👻", "dragon": "🐉",
    "dark": "🌑", "steel": "⚙️", "fairy": "✨",
}


def single_effectiveness(atk_type: str, def_type: str) -> float:
    return _CHART.get(atk_type, {}).get(def_type, 1.0)


def effectiveness(atk_type: str, defender_types: list[str]) -> float:
    """Multiplicador total de um ataque contra os tipos do defensor."""
    mult = 1.0
    for dt in defender_types:
        mult *= single_effectiveness(atk_type, dt)
    return mult


def effectiveness_label(mult: float) -> str:
    if mult == 0:
        return "Não tem efeito..."
    if mult >= 2:
        return "É super efetivo!"
    if mult > 1:
        return "É efetivo!"
    if mult < 1:
        return "Não é muito efetivo..."
    return ""


def type_color(types: list[str]) -> int:
    return TYPE_COLORS.get(types[0], 0xA8A77A) if types else 0xA8A77A
