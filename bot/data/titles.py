"""Títulos (cargos do Discord) de treinador por nível — temática pokémon.

A cada faixa de nível o jogador ganha um cargo novo (e perde o anterior).
15 títulos distribuídos do nível 1 ao 200, do mais fraco (Magikarp/Caterpie)
ao divino (Arceus). Edite à vontade os nomes/cores aqui.
"""
from __future__ import annotations

# (nível mínimo, nome do cargo, cor). Ordem crescente por nível.
TITLES: list[tuple[int, str, int]] = [
    (1,   "🥚 Novato de Pallet",     0x95A5A6),
    (10,  "🐛 Treinador Caterpie",   0x7FB069),
    (25,  "⚡ Domador Pikachu",       0xF1C40F),
    (40,  "🦊 Parceiro Eevee",        0xC9A26B),
    (55,  "🔥 Guardião Charizard",    0xE67E22),
    (70,  "👻 Espectro Gengar",       0x8E44AD),
    (85,  "🥋 Aura de Lucario",       0x2980B9),
    (100, "🐲 Cavaleiro Dragonite",   0xE39B3F),
    (115, "🌊 Fúria Gyarados",        0x2C6FBB),
    (130, "🪨 Coloso Tyranitar",      0x6B8E23),
    (145, "🦈 Predador Garchomp",     0x16A085),
    (160, "🤖 Mente Metagross",       0x5D6D7E),
    (175, "🕊️ Lenda Alada",           0x48C9B0),
    (190, "🧬 Poder Mewtwo",          0x9B59B6),
    (200, "🌌 Divindade Arceus",      0xF5D76E),
]

TITLE_NAMES = {name for _, name, _ in TITLES}


def title_for_level(level: int) -> tuple[int, str, int] | None:
    """Maior título cujo nível mínimo o jogador já alcançou."""
    chosen: tuple[int, str, int] | None = None
    for entry in TITLES:
        if level >= entry[0]:
            chosen = entry
        else:
            break
    return chosen
