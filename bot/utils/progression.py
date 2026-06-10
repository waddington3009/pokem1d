"""Definições e lógica de missões diárias e conquistas."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from bot.database.models import User


@dataclass(frozen=True)
class Quest:
    key: str
    description: str
    metric: str        # contador rastreado em quest_progress
    goal: int
    reward_coins: int
    reward_xp: int


# Missões diárias (resetam à meia-noite UTC).
DAILY_QUESTS: list[Quest] = [
    Quest("catch3", "Capture 3 pokémon", "catch", 3, 300, 30),
    Quest("catch10", "Capture 10 pokémon", "catch", 10, 800, 80),
    Quest("battle3", "Vença 3 batalhas", "battle_win", 3, 600, 60),
    Quest("evolve1", "Evolua 1 pokémon", "evolve", 1, 500, 50),
]


@dataclass(frozen=True)
class Achievement:
    key: str
    name: str
    description: str
    metric: str        # campo de User
    goal: int
    reward_coins: int


ACHIEVEMENTS: list[Achievement] = [
    Achievement("first_catch", "Primeiro Passo", "Capture seu 1º pokémon", "total_caught", 1, 100),
    Achievement("catch_50", "Colecionador", "Capture 50 pokémon", "total_caught", 50, 1000),
    Achievement("catch_250", "Mestre Pokémon", "Capture 250 pokémon", "total_caught", 250, 5000),
    Achievement("first_shiny", "Brilho Raro", "Capture seu 1º shiny", "total_shiny", 1, 2000),
    Achievement("shiny_5", "Caçador de Shinies", "Capture 5 shinies", "total_shiny", 5, 10000),
    Achievement("battle_10", "Veterano de Batalhas", "Vença 10 batalhas", "battles_won", 10, 1500),
    Achievement("battle_50", "Campeão", "Vença 50 batalhas", "battles_won", 50, 6000),
]

ACHIEVEMENTS_BY_KEY = {a.key: a for a in ACHIEVEMENTS}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def ensure_daily_reset(user: User) -> bool:
    """Reseta o progresso de missões se virou o dia. Retorna True se resetou."""
    progress = dict(user.quest_progress or {})
    today = _today()
    if progress.get("date") != today:
        user.quest_progress = {"date": today, "claimed": []}
        return True
    return False


def bump_quest(user: User, metric: str, amount: int = 1) -> None:
    """Incrementa um contador de missão diária."""
    ensure_daily_reset(user)
    progress = dict(user.quest_progress or {})
    progress[metric] = progress.get(metric, 0) + amount
    user.quest_progress = progress


def quest_state(user: User) -> list[tuple[Quest, int, bool, bool]]:
    """Retorna [(quest, progresso_atual, concluída, já_resgatada), ...]."""
    ensure_daily_reset(user)
    progress = user.quest_progress or {}
    claimed = set(progress.get("claimed", []))
    out = []
    for q in DAILY_QUESTS:
        current = min(progress.get(q.metric, 0), q.goal)
        done = current >= q.goal
        out.append((q, current, done, q.key in claimed))
    return out


def claim_quest(user: User, quest_key: str) -> Quest | None:
    """Marca a missão como resgatada se concluída e não resgatada. Retorna a Quest."""
    ensure_daily_reset(user)
    quest = next((q for q in DAILY_QUESTS if q.key == quest_key), None)
    if quest is None:
        return None
    progress = dict(user.quest_progress or {})
    claimed = list(progress.get("claimed", []))
    if quest.key in claimed:
        return None
    if progress.get(quest.metric, 0) < quest.goal:
        return None
    claimed.append(quest.key)
    progress["claimed"] = claimed
    user.quest_progress = progress
    return quest


def check_achievements(user: User) -> list[Achievement]:
    """Verifica e desbloqueia conquistas. Retorna as recém-desbloqueadas."""
    unlocked = set(user.achievements or [])
    newly: list[Achievement] = []
    for ach in ACHIEVEMENTS:
        if ach.key in unlocked:
            continue
        value = getattr(user, ach.metric, 0)
        if value >= ach.goal:
            unlocked.add(ach.key)
            newly.append(ach)
    if newly:
        user.achievements = list(unlocked)
    return newly
