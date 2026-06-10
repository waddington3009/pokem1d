"""Naturezas: cada uma sobe um atributo em 10% e baixa outro em 10%.

Atributos afetados: atk, def, spa, spd, spe (HP nunca é afetado).
Naturezas neutras têm up == down (efeito nulo).
"""
from __future__ import annotations

import random

# nome -> (atributo_aumentado, atributo_reduzido)
NATURES: dict[str, tuple[str, str]] = {
    "Hardy": ("atk", "atk"),
    "Lonely": ("atk", "def"),
    "Brave": ("atk", "spe"),
    "Adamant": ("atk", "spa"),
    "Naughty": ("atk", "spd"),
    "Bold": ("def", "atk"),
    "Docile": ("def", "def"),
    "Relaxed": ("def", "spe"),
    "Impish": ("def", "spa"),
    "Lax": ("def", "spd"),
    "Timid": ("spe", "atk"),
    "Hasty": ("spe", "def"),
    "Serious": ("spe", "spe"),
    "Jolly": ("spe", "spa"),
    "Naive": ("spe", "spd"),
    "Modest": ("spa", "atk"),
    "Mild": ("spa", "def"),
    "Quiet": ("spa", "spe"),
    "Bashful": ("spa", "spa"),
    "Rash": ("spa", "spd"),
    "Calm": ("spd", "atk"),
    "Gentle": ("spd", "def"),
    "Sassy": ("spd", "spe"),
    "Careful": ("spd", "spa"),
    "Quirky": ("spd", "spd"),
}

NATURE_NAMES = list(NATURES.keys())


def random_nature() -> str:
    return random.choice(NATURE_NAMES)


def nature_multiplier(nature: str, stat: str) -> float:
    """Retorna 1.1, 0.9 ou 1.0 conforme a natureza afeta o atributo."""
    up, down = NATURES.get(nature, ("", ""))
    if up == down:  # neutra
        return 1.0
    if stat == up:
        return 1.1
    if stat == down:
        return 0.9
    return 1.0


def nature_arrow(nature: str, stat: str) -> str:
    """Seta visual para exibir em embeds (↑ aumenta / ↓ reduz)."""
    up, down = NATURES.get(nature, ("", ""))
    if up == down:
        return ""
    if stat == up:
        return " ↑"
    if stat == down:
        return " ↓"
    return ""
