"""Registro de itens: pokébolas, pedras de evolução, incensos e boosters."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass


def _norm(text: str) -> str:
    """Normaliza para comparação: sem acento, minúsculo, sem espaço/hífen."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return "".join(c for c in text.lower() if c.isalnum())


@dataclass(frozen=True)
class Item:
    key: str
    name: str
    emoji: str
    category: str          # "ball" | "stone" | "lure" | "booster" | "misc"
    price: int             # preço na loja (0 = não vendável)
    description: str
    sellable: bool = True  # se pode ser vendido de volta (por metade do preço)
    # parâmetros específicos
    catch_iv_rolls: int = 1     # nº de rolagens de IV (pega a melhor) — pokébolas
    min_iv_floor: int = 0       # piso de IV garantido — masterball
    shiny_bonus: float = 1.0    # multiplicador na chance de shiny
    xp_amount: int = 0          # booster de XP
    level_amount: int = 0       # rare candy
    lure_minutes: int = 0       # duração do incenso
    stone: str | None = None    # tipo de pedra p/ evolução


ITEMS: dict[str, Item] = {
    # ---------------- Pokébolas (bônus automático na captura) ----------------
    "pokeball": Item(
        "pokeball", "Poké Ball", "⚪", "ball", 50,
        "Captura padrão. Sem bônus de IV.",
    ),
    "greatball": Item(
        "greatball", "Great Ball", "🔵", "ball", 200,
        "Na captura, rola os IVs 2× e mantém os melhores.",
        catch_iv_rolls=2, shiny_bonus=1.2,
    ),
    "ultraball": Item(
        "ultraball", "Ultra Ball", "🟡", "ball", 600,
        "Rola os IVs 3× e mantém os melhores. +chance de shiny.",
        catch_iv_rolls=3, shiny_bonus=1.5,
    ),
    "masterball": Item(
        "masterball", "Master Ball", "🟣", "ball", 25000,
        "Garante IVs altos (piso 25) e dobra a chance de shiny.",
        catch_iv_rolls=4, min_iv_floor=25, shiny_bonus=2.0, sellable=False,
    ),

    # ---------------- Pedras de evolução ----------------
    "fire-stone": Item("fire-stone", "Fire Stone", "🔥", "stone", 1500,
                       "Evolui certos pokémon de Fogo.", stone="fire"),
    "water-stone": Item("water-stone", "Water Stone", "💧", "stone", 1500,
                        "Evolui certos pokémon de Água.", stone="water"),
    "thunder-stone": Item("thunder-stone", "Thunder Stone", "⚡", "stone", 1500,
                          "Evolui certos pokémon Elétricos.", stone="thunder"),
    "leaf-stone": Item("leaf-stone", "Leaf Stone", "🍃", "stone", 1500,
                       "Evolui certos pokémon de Planta.", stone="leaf"),
    "moon-stone": Item("moon-stone", "Moon Stone", "🌙", "stone", 1500,
                       "Evolui certos pokémon.", stone="moon"),
    "sun-stone": Item("sun-stone", "Sun Stone", "☀️", "stone", 1500,
                      "Evolui certos pokémon.", stone="sun"),
    "dawn-stone": Item("dawn-stone", "Dawn Stone", "🌅", "stone", 1800,
                       "Evolui certos pokémon (ex.: Kirlia, Snorunt).", stone="dawn"),
    "dusk-stone": Item("dusk-stone", "Dusk Stone", "🌑", "stone", 1800,
                       "Evolui certos pokémon (ex.: Murkrow, Misdreavus).", stone="dusk"),
    "shiny-stone": Item("shiny-stone", "Shiny Stone", "🌟", "stone", 1800,
                        "Evolui certos pokémon (ex.: Togetic, Roselia).", stone="shiny"),

    # ---------------- Incenso / lure ----------------
    "incense": Item(
        "incense", "Incenso", "🪔", "lure", 1000,
        "Acelera os spawns no canal por 30 minutos.",
        lure_minutes=30, sellable=False,
    ),

    # ---------------- Boosters ----------------
    "rare-candy": Item(
        "rare-candy", "Rare Candy", "🍬", "booster", 800,
        "Sobe +1 nível do pokémon selecionado.",
        level_amount=1, sellable=False,
    ),
    "xp-booster": Item(
        "xp-booster", "XP Booster", "📈", "booster", 500,
        "Concede 100 XP ao pokémon selecionado.",
        xp_amount=100, sellable=False,
    ),
}

# Itens que aparecem na loja (ordem de exibição)
SHOP_ORDER = [
    "pokeball", "greatball", "ultraball", "masterball",
    "fire-stone", "water-stone", "thunder-stone", "leaf-stone", "moon-stone", "sun-stone",
    "dawn-stone", "dusk-stone", "shiny-stone",
    "incense", "rare-candy", "xp-booster",
]


def get_item(key: str) -> Item | None:
    return ITEMS.get(key.lower().strip())


def find_item(query: str) -> Item | None:
    """Busca por key ou por nome — tolerante a acento, maiúsculas, espaços e hífens.

    Aceita: 'thunder-stone', 'Thunder Stone', 'thunderstone', 'Poké Ball', 'poke ball'...
    """
    key = _norm(query)
    if not key:
        return None
    for item in ITEMS.values():
        if _norm(item.key) == key or _norm(item.name) == key:
            return item
    return None


def split_item_and_quantity(text: str) -> tuple[str, int | None]:
    """Separa um nome de item (com espaços) de um número opcional no final.

    'Thunder Stone 5' -> ('Thunder Stone', 5)
    'Great Ball'      -> ('Great Ball', None)
    """
    parts = text.rsplit(None, 1)
    if len(parts) == 2 and parts[1].lstrip("-").isdigit():
        return parts[0].strip(), int(parts[1])
    return text.strip(), None


def best_ball(owned: dict[str, int]) -> Item | None:
    """Melhor pokébola que o usuário possui (para bônus automático na captura)."""
    for key in ("masterball", "ultraball", "greatball"):
        if owned.get(key, 0) > 0:
            return ITEMS[key]
    return None
