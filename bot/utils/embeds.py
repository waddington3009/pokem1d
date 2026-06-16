"""Construtores de embeds reutilizáveis."""
from __future__ import annotations

import discord

from config import settings
from bot.data.natures import nature_arrow
from bot.data.pokemon_data import Species
from bot.data.types import TYPE_EMOJI, type_color
from bot.utils import rarity as rarity_mod
from bot.utils.stats import STAT_KEYS, compute_all_stats, iv_grade

STAT_LABEL = {
    "hp": "HP", "atk": "Atk", "def": "Def",
    "spa": "SpA", "spd": "SpD", "spe": "Spe",
}


def species_name(species: Species, shiny: bool = False, nickname: str | None = None) -> str:
    base = nickname or species.name
    return f"✨ {base}" if shiny else base


def types_line(species: Species) -> str:
    return " ".join(f"{TYPE_EMOJI.get(t, '')} {t.title()}" for t in species.types)


def ok_embed(title: str, description: str = "") -> discord.Embed:
    return discord.Embed(title=title, description=description, color=settings.color_success)


def err_embed(description: str, title: str = "Ops!") -> discord.Embed:
    return discord.Embed(title=f"❌ {title}", description=description, color=settings.color_error)


def info_text(description: str, title: str = "") -> discord.Embed:
    return discord.Embed(title=title, description=description, color=settings.color_info)


def spawn_embed(species: Species, shiny: bool, prefix: str = "p!") -> discord.Embed:
    """Embed do pokémon selvagem que apareceu (sem revelar o nome)."""
    color = settings.color_shiny if shiny else type_color(species.types)
    desc = (
        "Um **pokémon selvagem** apareceu! 🌿\n"
        "Adivinhe quem é e use **`/capturar <nome>`** para capturá-lo!"
    )
    embed = discord.Embed(
        title="Quem é esse Pokémon?",
        description=desc,
        color=color,
    )
    embed.set_image(url=settings.sprite(species.id, shiny=shiny, official=True))
    if shiny:
        embed.set_footer(text="✨ Há algo de diferente neste...")
    return embed


def catch_embed(
    species: Species, pokemon, trainer: str, coins: int, shiny: bool,
    new_dex: bool,
) -> discord.Embed:
    color = settings.color_shiny if shiny else settings.color_success
    name = species_name(species, shiny)
    embed = discord.Embed(
        title=f"Você capturou {name}!",
        color=color,
    )
    embed.description = (
        f"**{trainer}** capturou um **{name}** "
        f"(Nível {pokemon.level}) — {rarity_mod.RARITY_EMOJI.get(species.rarity, '')} "
        f"{rarity_mod.rarity_label(species.rarity)}\n\n"
        f"📊 IV total: **{pokemon.iv_percent:.1f}%** ({iv_grade(pokemon.iv_percent)})\n"
        f"💰 Recompensa: **{coins}** PokéCoins"
    )
    if new_dex:
        embed.description += "\n📕 **Novo registro na Pokédex!**"
    if shiny:
        embed.description += "\n✨ **SHINY!** Que sorte incrível!"
    embed.set_thumbnail(url=settings.sprite_animated(species.id, shiny=shiny))
    embed.set_footer(text=f"#{pokemon.idx} • {species.name}")
    return embed


def info_embed(species: Species, pokemon, language: str = "pt") -> discord.Embed:
    """Cartão detalhado de um pokémon possuído."""
    color = settings.color_shiny if pokemon.shiny else type_color(species.types)
    stats = compute_all_stats(species, pokemon)

    title = species_name(species, pokemon.shiny, pokemon.nickname)
    embed = discord.Embed(title=f"#{pokemon.idx} — {title}", color=color)
    embed.set_thumbnail(url=settings.sprite_animated(species.id, shiny=pokemon.shiny))

    embed.add_field(name="Espécie", value=f"#{species.id:03d} {species.name}", inline=True)
    embed.add_field(name="Tipo", value=types_line(species), inline=True)
    embed.add_field(
        name="Raridade",
        value=f"{rarity_mod.RARITY_EMOJI.get(species.rarity,'')} {rarity_mod.rarity_label(species.rarity)}",
        inline=True,
    )

    embed.add_field(name="Nível", value=f"{pokemon.level}", inline=True)
    embed.add_field(name="XP", value=f"{pokemon.xp}/{pokemon.xp_to_next}", inline=True)
    embed.add_field(name="Natureza", value=pokemon.nature, inline=True)

    # bloco de atributos com IV e seta de natureza
    lines = []
    iv_map = {
        "hp": pokemon.iv_hp, "atk": pokemon.iv_atk, "def": pokemon.iv_def,
        "spa": pokemon.iv_spa, "spd": pokemon.iv_spd, "spe": pokemon.iv_spe,
    }
    for key in STAT_KEYS:
        arrow = nature_arrow(pokemon.nature, key)
        lines.append(
            f"`{STAT_LABEL[key]:<3}` **{stats[key]:>4}**  "
            f"(IV {iv_map[key]:>2}/31){arrow}"
        )
    embed.add_field(name="Atributos", value="\n".join(lines), inline=False)
    embed.add_field(
        name="IV Total",
        value=f"**{pokemon.iv_percent:.2f}%** — {iv_grade(pokemon.iv_percent)}",
        inline=True,
    )
    embed.add_field(
        name="Golpes",
        value=", ".join(m.replace("-", " ").title() for m in species.moves),
        inline=False,
    )
    flags = []
    if pokemon.favorite:
        flags.append("❤️ Favorito")
    if pokemon.held_item:
        flags.append(f"🎒 {pokemon.held_item}")
    if flags:
        embed.set_footer(text=" • ".join(flags))
    return embed
