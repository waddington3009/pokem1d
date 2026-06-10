"""Geração de IVs, cálculo de atributos e progressão de XP/nível."""
from __future__ import annotations

import random

from bot.data.natures import nature_multiplier
from bot.data.pokemon_data import Species

IV_KEYS = ["iv_hp", "iv_atk", "iv_def", "iv_spa", "iv_spd", "iv_spe"]
STAT_KEYS = ["hp", "atk", "def", "spa", "spd", "spe"]
MAX_LEVEL = 100


def random_iv(floor: int = 0) -> int:
    return random.randint(max(0, floor), 31)


def generate_ivs(rolls: int = 1, floor: int = 0) -> dict[str, int]:
    """Gera os 6 IVs. Com `rolls`>1, gera N conjuntos e mantém o de maior total.

    `floor` garante um valor mínimo por IV (usado pela Master Ball).
    """
    best: dict[str, int] | None = None
    best_total = -1
    for _ in range(max(1, rolls)):
        ivs = {k: random_iv(floor) for k in IV_KEYS}
        total = sum(ivs.values())
        if total > best_total:
            best_total = total
            best = ivs
    assert best is not None
    return best


def compute_stat(base: int, iv: int, level: int, nature_mult: float, is_hp: bool) -> int:
    """Fórmula padrão de cálculo de atributo (sem EVs)."""
    if is_hp:
        return (2 * base + iv) * level // 100 + level + 10
    val = (2 * base + iv) * level // 100 + 5
    return int(val * nature_mult)


def compute_all_stats(species: Species, pokemon) -> dict[str, int]:
    """Calcula os 6 atributos finais de um pokémon possuído."""
    ivs = {
        "hp": pokemon.iv_hp, "atk": pokemon.iv_atk, "def": pokemon.iv_def,
        "spa": pokemon.iv_spa, "spd": pokemon.iv_spd, "spe": pokemon.iv_spe,
    }
    out: dict[str, int] = {}
    for stat in STAT_KEYS:
        base = species.base_stats[stat]
        is_hp = stat == "hp"
        mult = 1.0 if is_hp else nature_multiplier(pokemon.nature, stat)
        out[stat] = compute_stat(base, ivs[stat], pokemon.level, mult, is_hp)
    return out


def max_hp(species: Species, pokemon) -> int:
    return compute_stat(species.base_stats["hp"], pokemon.iv_hp, pokemon.level, 1.0, True)


def xp_for_level(level: int) -> int:
    """XP necessário para sair do nível `level` para o próximo."""
    return level * 25 + 50


def apply_xp(level: int, xp: int, amount: int) -> tuple[int, int, int]:
    """Adiciona XP e processa level-ups.

    Retorna (novo_nível, novo_xp, níveis_ganhos).
    """
    if level >= MAX_LEVEL:
        return level, 0, 0
    xp += amount
    gained = 0
    while level < MAX_LEVEL and xp >= xp_for_level(level):
        xp -= xp_for_level(level)
        level += 1
        gained += 1
    if level >= MAX_LEVEL:
        xp = 0
    return level, xp, gained


def iv_grade(percent: float) -> str:
    """Rótulo qualitativo do IV total (estilo 'avaliador')."""
    if percent >= 98:
        return "🌟 Perfeito"
    if percent >= 90:
        return "💎 Excelente"
    if percent >= 75:
        return "✨ Ótimo"
    if percent >= 55:
        return "👍 Bom"
    if percent >= 35:
        return "🆗 Mediano"
    return "🥉 Fraco"
