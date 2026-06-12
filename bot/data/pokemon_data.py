"""Carrega o dataset de espécies (data/pokemon.json) e oferece consultas."""
from __future__ import annotations

import json
import random
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from config import DATA_DIR

from .moves import build_moveset

# Pokémon fracos de propósito (lore): mantêm um moveset mínimo.
WEAK_MOVESETS = {129: ["tackle"], 132: ["tackle"]}  # Magikarp, Ditto


def normalize_name(text: str) -> str:
    """Minúsculas, sem acento, sem caracteres especiais — para comparar nomes."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return "".join(c for c in text.lower() if c.isalnum())


@dataclass
class EvolutionStep:
    to: int
    method: str           # "level" | "stone" | "trade" | "friendship"
    level: int | None = None
    stone: str | None = None


@dataclass
class Species:
    id: int
    name: str
    types: list[str]
    base_stats: dict[str, int]
    rarity: str = "common"
    legendary: bool = False
    mythical: bool = False
    starter: bool = False
    alt_names: list[str] = field(default_factory=list)
    evolutions: list[EvolutionStep] = field(default_factory=list)
    moves: list[str] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)

    @property
    def base_total(self) -> int:
        return sum(self.base_stats.values())

    def display_name(self, language: str = "pt") -> str:
        return self.names.get(language, self.name)

    def can_evolve_by_level(self, level: int) -> EvolutionStep | None:
        for ev in self.evolutions:
            if ev.method == "level" and ev.level is not None and level >= ev.level:
                return ev
        return None

    def can_evolve_by_stone(self, stone: str) -> EvolutionStep | None:
        for ev in self.evolutions:
            if ev.method == "stone" and ev.stone == stone:
                return ev
        return None


class Pokedex:
    """Registro global de espécies + índice de busca por nome."""

    def __init__(self) -> None:
        self.species: dict[int, Species] = {}
        self._name_index: dict[str, int] = {}

    # -------- carregamento --------
    def load(self, path: Path | None = None) -> None:
        path = path or (DATA_DIR / "pokemon.json")
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        for entry in raw:
            self._add(entry)
        self._build_index()

    def _add(self, entry: dict) -> None:
        evolutions = [
            EvolutionStep(
                to=e["to"], method=e.get("method", "level"),
                level=e.get("level"), stone=e.get("stone"),
            )
            for e in entry.get("evolution", [])
        ]
        types = entry["types"]
        # moveset coerente com o tipo (remove golpes fora de tipo)
        if entry["id"] in WEAK_MOVESETS:
            moves = WEAK_MOVESETS[entry["id"]]
        else:
            moves = build_moveset(types, entry.get("moves"))
            # lendários/míticos: mantêm 2 STAB + ganham cobertura quase universal
            # (Earthquake + Dazzling Gleam) para nunca ficarem "paredados" por tipo
            if entry.get("legendary") or entry.get("mythical"):
                final: list[str] = []
                for k in moves[:2] + ["earthquake", "dazzling-gleam"]:
                    if k not in final:
                        final.append(k)
                for k in moves:
                    if len(final) >= 4:
                        break
                    if k not in final:
                        final.append(k)
                moves = final[:4]
        sp = Species(
            id=entry["id"],
            name=entry["name"],
            types=types,
            base_stats=entry["base_stats"],
            rarity=entry.get("rarity", "common"),
            legendary=entry.get("legendary", False),
            mythical=entry.get("mythical", False),
            starter=entry.get("starter", False),
            alt_names=entry.get("alt_names", []),
            evolutions=evolutions,
            moves=moves,
            names=entry.get("names", {}),
        )
        self.species[sp.id] = sp

    def _build_index(self) -> None:
        self._name_index.clear()
        for sp in self.species.values():
            keys = {sp.name, *sp.alt_names, *sp.names.values()}
            for key in keys:
                self._name_index[normalize_name(key)] = sp.id

    # -------- consultas --------
    def get(self, species_id: int) -> Species | None:
        return self.species.get(species_id)

    def by_name(self, query: str) -> Species | None:
        sid = self._name_index.get(normalize_name(query))
        return self.species.get(sid) if sid is not None else None

    def all(self) -> list[Species]:
        return sorted(self.species.values(), key=lambda s: s.id)

    def count(self) -> int:
        return len(self.species)

    def by_rarity(self, rarity: str) -> list[Species]:
        return [s for s in self.species.values() if s.rarity == rarity]

    def random_starter(self) -> Species:
        starters = [s for s in self.species.values() if s.starter]
        return random.choice(starters) if starters else random.choice(list(self.species.values()))


# Instância global, carregada na inicialização do bot.
POKEDEX = Pokedex()
