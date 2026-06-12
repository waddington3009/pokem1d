"""Configuração central do bot. Carrega variáveis de ambiente do .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Raiz do projeto
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
ASSETS_DIR = BASE_DIR / "assets"

load_dotenv(BASE_DIR / ".env")


def _parse_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


@dataclass(frozen=True)
class Settings:
    token: str = os.getenv("DISCORD_TOKEN", "")
    default_prefix: str = os.getenv("DEFAULT_PREFIX", "p!")
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///pokebot.db")
    owner_ids: set[int] = field(default_factory=lambda: _parse_ids(os.getenv("OWNER_IDS")))
    default_language: str = os.getenv("DEFAULT_LANGUAGE", "pt")

    # ---- Parâmetros de jogo (ajustáveis) ----
    # Spawn
    spawn_min_messages: int = 12       # mínimo de mensagens p/ tentar spawnar
    spawn_max_messages: int = 35       # máximo (escolhido aleatório no intervalo)
    spawn_despawn_seconds: int = 600   # tempo até o pokémon sumir (10 min)
    spawn_cooldown_seconds: int = 20   # tempo mínimo entre spawns no mesmo canal

    # Captura
    shiny_chance: int = 4000           # 1 em N
    catch_coins_min: int = 25
    catch_coins_max: int = 60
    catch_xp: int = 35

    # Exploração (comando p!explore)
    explore_cooldown_seconds: int = 12     # cooldown por usuário
    explore_nothing_chance: float = 0.28   # chance de não achar nada
    explore_coins_chance: float = 0.12     # chance de achar moedas (em vez de pokémon)
    explore_coins_min: int = 30
    explore_coins_max: int = 140

    # Loot (caixa que cai junto com os spawns)
    loot_chance: float = 0.18          # chance do spawn ser uma caixa de loot
    loot_coins_chance: float = 0.6     # no loot, chance de vir moedas (senão item)
    loot_coins_min: int = 1000         # mínimo de moedas (sempre > 1000)
    loot_coins_max: int = 6000
    loot_despawn_seconds: int = 300    # a caixa some em 5 min se ninguém coletar
    # imagem/gif da caixa — troque por qualquer URL (suba no Discord e copie o link)
    loot_image_url: str = (
        "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f381.png"
    )

    # Economia
    daily_base: int = 200
    daily_streak_bonus: int = 50       # bônus por dia de streak
    daily_streak_max_bonus: int = 1000

    # Sprites (CDN oficial do PokéAPI — sem precisar processar imagem localmente)
    sprite_url: str = (
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{id}.png"
    )
    sprite_shiny_url: str = (
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
        "sprites/pokemon/shiny/{id}.png"
    )
    sprite_official_url: str = (
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
        "sprites/pokemon/other/official-artwork/{id}.png"
    )
    sprite_official_shiny_url: str = (
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
        "sprites/pokemon/other/official-artwork/shiny/{id}.png"
    )
    # Sprites animados (GIF) da Gen 5 — disponíveis para id <= 649
    sprite_animated_url: str = (
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
        "sprites/pokemon/versions/generation-v/black-white/animated/{id}.gif"
    )
    sprite_animated_shiny_url: str = (
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
        "sprites/pokemon/versions/generation-v/black-white/animated/shiny/{id}.gif"
    )

    # Cores (embeds)
    color_default: int = 0xE3350D       # vermelho pokébola
    color_success: int = 0x57F287
    color_error: int = 0xED4245
    color_shiny: int = 0xFFD700
    color_info: int = 0x5865F2

    def sprite(self, species_id: int, shiny: bool = False, official: bool = False) -> str:
        if official:
            tmpl = self.sprite_official_shiny_url if shiny else self.sprite_official_url
        else:
            tmpl = self.sprite_shiny_url if shiny else self.sprite_url
        return tmpl.format(id=species_id)

    def sprite_animated(self, species_id: int, shiny: bool = False) -> str:
        """GIF animado (Gen 5). Cai para o sprite estático se não houver animação."""
        if species_id > 649:
            return self.sprite(species_id, shiny=shiny)
        tmpl = self.sprite_animated_shiny_url if shiny else self.sprite_animated_url
        return tmpl.format(id=species_id)


settings = Settings()
