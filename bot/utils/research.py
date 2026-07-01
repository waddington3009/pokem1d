"""Pesquisa de Campo: acúmulo de RP (Research Points) com teto diário e a Caçada.

Substitui o "gacha" de lendários no explore. RP enche uma barra; ao encher, o
jogador faz uma Caçada (batalha contra o lendário → captura ao vencer).
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


def rp_remaining_today(user: User) -> int:
    """Quanto de RP ainda dá pra ganhar hoje (teto diário)."""
    _reset_daily_if_needed(user)
    return max(0, settings.research_daily_cap - (user.research_today or 0))


def grant_rp(user: User, amount: int) -> int:
    """Concede RP respeitando o teto diário. Retorna quanto foi realmente concedido."""
    if amount <= 0:
        return 0
    _reset_daily_if_needed(user)
    room = rp_remaining_today(user)
    gained = min(amount, room)
    if gained > 0:
        user.research_points = (user.research_points or 0) + gained
        user.research_today = (user.research_today or 0) + gained
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
