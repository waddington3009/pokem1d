"""Pesquisa de Campo: acúmulo de RP (Research Points) com retorno decrescente e a Caçada.

Substitui o "gacha" de lendários no explore. RP enche uma barra; ao encher, o
jogador faz uma Caçada (batalha contra o lendário → captura ao vencer).

Não há teto rígido: até o *soft cap* diário o RP rende cheio; depois disso os
ganhos ficam reduzidos (settings.research_reduced_factor). Reseta a cada dia.
"""
from __future__ import annotations

from datetime import datetime, timezone

from config import settings
from bot.database.models import User


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _reset_daily_if_needed(user: User) -> None:
    if user.research_day != _today():
        user.research_day = _today()
        user.research_today = 0


def rp_earned_today(user: User) -> int:
    """Quanto de RP o jogador já ganhou hoje."""
    _reset_daily_if_needed(user)
    return user.research_today or 0


def rp_reduced_active(user: User) -> bool:
    """True se o jogador já passou do soft cap diário e ganha RP reduzido."""
    soft = settings.research_soft_cap
    return soft > 0 and rp_earned_today(user) >= soft


def rp_until_reduced(user: User) -> int:
    """Quanto de RP ainda rende a valor cheio hoje (0 = já está no reduzido)."""
    soft = settings.research_soft_cap
    if soft <= 0:
        return 0
    return max(0, soft - rp_earned_today(user))


def grant_rp(user: User, amount: int) -> int:
    """Concede RP com retorno decrescente após o soft cap diário (sem teto rígido).

    Até o soft cap o RP rende cheio; a parte que passa do cap é multiplicada por
    settings.research_reduced_factor. Retorna quanto foi realmente concedido.
    """
    if amount <= 0:
        return 0
    _reset_daily_if_needed(user)
    today = user.research_today or 0
    soft = settings.research_soft_cap
    factor = settings.research_reduced_factor

    if soft <= 0 or factor >= 1.0:
        gained = amount
    elif today >= soft:
        gained = max(1, int(amount * factor + 0.5))
    else:
        room_full = soft - today
        if amount <= room_full:
            gained = amount
        else:
            over = amount - room_full
            gained = room_full + max(1, int(over * factor + 0.5))

    user.research_points = (user.research_points or 0) + gained
    user.research_today = today + gained
    return gained


def hunt_cost(user: User) -> int:
    """Custo (RP) da próxima Caçada Lendária — escala a cada caçada já feita."""
    return settings.hunt_base_cost + (user.hunts_won or 0) * settings.hunt_cost_step


def mythic_cost() -> int:
    return settings.mythic_hunt_cost


def mythic_unlocked(user: User) -> bool:
    return (user.hunts_won or 0) >= settings.mythic_unlock_hunts


def progress(user: User) -> tuple[int, int, float]:
    """(RP atual, custo da próxima caçada, fração 0..1) — para a barra."""
    cost = hunt_cost(user)
    pts = min(user.research_points or 0, cost)
    return pts, cost, (pts / cost if cost else 0.0)
