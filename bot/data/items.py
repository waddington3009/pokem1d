"""Registro de itens: pokébolas, pedras de evolução, incensos e boosters."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from bot.data.mega import MEGA_FORMS


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
    # "ball" | "stone" | "lure" | "booster" | "misc"
    # | "medicine" (cura/PP/reviver) | "battle" (X-items) | "mega-stone"
    category: str
    price: int             # preço na loja (0 = não vendável)
    description: str
    sellable: bool = True  # se pode ser vendido de volta (por metade do preço)
    # parâmetros específicos
    catch_iv_rolls: int = 1     # nº de rolagens de IV (pega a melhor) — pokébolas
    min_iv_floor: int = 0       # piso de IV garantido — masterball
    shiny_bonus: float = 1.0    # multiplicador na chance de shiny
    xp_amount: int = 0          # booster de XP
    level_amount: int = 0       # rare candy
    iv_boost: int = 0           # +N em cada IV (item premium)
    lure_minutes: int = 0       # duração do incenso
    stone: str | None = None    # tipo de pedra p/ evolução
    # ---- itens de batalha (usados no botão 🎒 Mochila da batalha) ----
    heal: int = 0               # HP fixo curado (-1 = HP total)
    cures: tuple[str, ...] = ()  # status curados; ("any",) = qualquer
    revive: float = 0.0         # fração de HP ao reviver (0 = não revive)
    pp_restore: int = 0         # +PP (-1 = total)
    pp_all: bool = False        # aplica o pp_restore a TODOS os golpes
    battle_stat: str | None = None  # atk/def/spa/spd/spe (X-item)
    battle_stage: int = 0       # nº de estágios concedidos (+1)
    usable_in_battle: bool = False  # aparece na 🎒 Mochila durante a batalha
    mega_stone: bool = False    # é uma Mega Stone (item segurável)

    @property
    def holdable(self) -> bool:
        """Pode ser 'segurado' por um pokémon (held item)."""
        return self.mega_stone


ITEMS: dict[str, Item] = {
    # ---------------- Pokébolas (bônus automático na captura) ----------------
    "pokeball": Item(
        "pokeball", "Poké Ball", "⚪", "ball", 90,
        "Captura padrão. Sem bônus de IV.",
    ),
    "greatball": Item(
        "greatball", "Great Ball", "🔵", "ball", 360,
        "Na captura, rola os IVs 2× e mantém os melhores.",
        catch_iv_rolls=2, shiny_bonus=1.2,
    ),
    "ultraball": Item(
        "ultraball", "Ultra Ball", "🟡", "ball", 1050,
        "Rola os IVs 3× e mantém os melhores. +chance de shiny.",
        catch_iv_rolls=3, shiny_bonus=1.5,
    ),
    "masterball": Item(
        "masterball", "Master Ball", "🟣", "ball", 40000,
        "Garante IVs altos (piso 25) e dobra a chance de shiny.",
        catch_iv_rolls=4, min_iv_floor=25, shiny_bonus=2.0, sellable=False,
    ),

    # ---------------- Pedras de evolução ----------------
    "fire-stone": Item("fire-stone", "Fire Stone", "🔥", "stone", 2600,
                       "Evolui certos pokémon de Fogo.", stone="fire"),
    "water-stone": Item("water-stone", "Water Stone", "💧", "stone", 2600,
                        "Evolui certos pokémon de Água.", stone="water"),
    "thunder-stone": Item("thunder-stone", "Thunder Stone", "⚡", "stone", 2600,
                          "Evolui certos pokémon Elétricos.", stone="thunder"),
    "leaf-stone": Item("leaf-stone", "Leaf Stone", "🍃", "stone", 2600,
                       "Evolui certos pokémon de Planta.", stone="leaf"),
    "moon-stone": Item("moon-stone", "Moon Stone", "🌙", "stone", 2600,
                       "Evolui certos pokémon.", stone="moon"),
    "sun-stone": Item("sun-stone", "Sun Stone", "☀️", "stone", 2600,
                      "Evolui certos pokémon.", stone="sun"),
    "dawn-stone": Item("dawn-stone", "Dawn Stone", "🌅", "stone", 3100,
                       "Evolui certos pokémon (ex.: Kirlia, Snorunt).", stone="dawn"),
    "dusk-stone": Item("dusk-stone", "Dusk Stone", "🌑", "stone", 3100,
                       "Evolui certos pokémon (ex.: Murkrow, Misdreavus).", stone="dusk"),
    "shiny-stone": Item("shiny-stone", "Shiny Stone", "🌟", "stone", 3100,
                        "Evolui certos pokémon (ex.: Togetic, Roselia).", stone="shiny"),
    "bond-ribbon": Item("bond-ribbon", "Laço da Amizade", "🎀", "stone", 3100,
                        "Evolui Eevee para Sylveon pelo forte laço de amizade.", stone="bond"),

    # ---------------- Incenso / lure ----------------
    "incense": Item(
        "incense", "Incenso", "🪔", "lure", 1800,
        "Acelera os spawns no canal por 30 minutos.",
        lure_minutes=30, sellable=False,
    ),

    # ---------------- Boosters ----------------
    "rare-candy": Item(
        "rare-candy", "Rare Candy", "🍬", "booster", 1400,
        "Sobe +1 nível do pokémon selecionado.",
        level_amount=1, sellable=False,
    ),
    "xp-booster": Item(
        "xp-booster", "XP Booster", "📈", "booster", 900,
        "Concede 100 XP ao pokémon selecionado.",
        xp_amount=100, sellable=False,
    ),
    "iv-crystal": Item(
        "iv-crystal", "Cristal de Potencial", "💠", "booster", 90000,
        "💎 PREMIUM: aumenta **+1 em cada IV** do pokémon (até o máximo de 31). "
        "Use várias vezes para aperfeiçoar um favorito.",
        iv_boost=1, sellable=False,
    ),

    # ---------------- Medicina: cura de HP (usável na 🎒 Mochila da batalha) ----
    "potion": Item("potion", "Poção", "🧪", "medicine", 2000,
                   "Cura +20 HP em batalha.", heal=20, usable_in_battle=True),
    "super-potion": Item("super-potion", "Super Poção", "🧪", "medicine", 5000,
                         "Cura +60 HP em batalha.", heal=60, usable_in_battle=True),
    "hyper-potion": Item("hyper-potion", "Hyper Poção", "🧴", "medicine", 15500,
                         "Cura +120 HP em batalha.", heal=120, usable_in_battle=True),
    "max-potion": Item("max-potion", "Poção Máxima", "🧴", "medicine", 20800,
                       "Restaura TODO o HP em batalha.", heal=-1, usable_in_battle=True),
    "full-restore": Item("full-restore", "Restaurador Total", "💉", "medicine", 40000,
                         "Restaura TODO o HP **e** cura qualquer status.",
                         heal=-1, cures=("any",), usable_in_battle=True),
    # ---------------- Medicina: cura de status ----------------
    "antidote": Item("antidote", "Antídoto", "🟢", "medicine", 1200,
                     "Cura veneno.", cures=("poison",), usable_in_battle=True),
    "burn-heal": Item("burn-heal", "Antiqueimadura", "🔥", "medicine", 1200,
                      "Cura queimadura.", cures=("burn",), usable_in_battle=True),
    "paralyze-heal": Item("paralyze-heal", "Antiparalisia", "⚡", "medicine", 1200,
                          "Cura paralisia.", cures=("paralyze",), usable_in_battle=True),
    "awakening": Item("awakening", "Despertar", "😴", "medicine", 1200,
                      "Cura sono.", cures=("sleep",), usable_in_battle=True),
    "ice-heal": Item("ice-heal", "Antigelo", "❄️", "medicine", 1200,
                     "Cura congelamento.", cures=("freeze",), usable_in_battle=True),
    "full-heal": Item("full-heal", "Cura Total", "💊", "medicine", 4000,
                      "Cura qualquer status.", cures=("any",), usable_in_battle=True),
    # ---------------- Medicina: restaurar PP ----------------
    "ether": Item("ether", "Éter", "🔵", "medicine", 2500,
                  "Restaura +10 PP do golpe com menos PP.", pp_restore=10, usable_in_battle=True),
    "max-ether": Item("max-ether", "Éter Máximo", "🔷", "medicine", 6000,
                      "Restaura todo o PP do golpe com menos PP.", pp_restore=-1, usable_in_battle=True),
    "elixir": Item("elixir", "Elixir", "🟣", "medicine", 9000,
                   "Restaura +10 PP de TODOS os golpes.", pp_restore=10, pp_all=True, usable_in_battle=True),
    "max-elixir": Item("max-elixir", "Elixir Máximo", "🟪", "medicine", 20000,
                       "Restaura todo o PP de TODOS os golpes.", pp_restore=-1, pp_all=True, usable_in_battle=True),
    # ---------------- Medicina: reviver (ainda NÃO usável em batalha) ----------------
    "revive": Item("revive", "Reviver", "✨", "medicine", 30000,
                   "Revive um pokémon desmaiado com 50% do HP. "
                   "*(uso em batalha chega em breve)*", revive=0.5, usable_in_battle=False),
    "max-revive": Item("max-revive", "Reviver Máximo", "🌟", "medicine", 60000,
                       "Revive um pokémon desmaiado com HP total. "
                       "*(uso em batalha chega em breve)*", revive=1.0, usable_in_battle=False),
    # ---------------- Itens de batalha: X-items (usam os estágios do motor) ------
    "x-attack": Item("x-attack", "X Ataque", "⚔️", "battle", 2500,
                     "+1 estágio de Ataque em batalha.", battle_stat="atk", battle_stage=1, usable_in_battle=True),
    "x-defense": Item("x-defense", "X Defesa", "🛡️", "battle", 2500,
                      "+1 estágio de Defesa em batalha.", battle_stat="def", battle_stage=1, usable_in_battle=True),
    "x-sp-atk": Item("x-sp-atk", "X Atq. Esp.", "🔮", "battle", 2500,
                     "+1 estágio de Ataque Especial em batalha.", battle_stat="spa", battle_stage=1, usable_in_battle=True),
    "x-sp-def": Item("x-sp-def", "X Def. Esp.", "🔰", "battle", 2500,
                     "+1 estágio de Defesa Especial em batalha.", battle_stat="spd", battle_stage=1, usable_in_battle=True),
    "x-speed": Item("x-speed", "X Velocidade", "💨", "battle", 2500,
                    "+1 estágio de Velocidade em batalha.", battle_stat="spe", battle_stage=1, usable_in_battle=True),
}

# ---------------- Mega Stones (geradas a partir de bot/data/mega.py) ----------------
# Item segurável: em batalha, permite Mega Evoluir (1x). Não é consumida.
for _mf in MEGA_FORMS.values():
    ITEMS[_mf.stone_key] = Item(
        _mf.stone_key, _mf.stone_name, _mf.emoji, "mega-stone", 50000,
        f"Segure em **{_mf.base_name}** para Mega Evoluir ({_mf.mega_name}) durante a batalha.",
        sellable=False, mega_stone=True,
    )

# Itens que aparecem na loja (ordem de exibição)
SHOP_ORDER = [
    "pokeball", "greatball", "ultraball", "masterball",
    # medicina (cura/status/PP/reviver)
    "potion", "super-potion", "hyper-potion", "max-potion", "full-restore",
    "antidote", "burn-heal", "paralyze-heal", "awakening", "ice-heal", "full-heal",
    "ether", "max-ether", "elixir", "max-elixir", "revive", "max-revive",
    # itens de batalha (X-items)
    "x-attack", "x-defense", "x-sp-atk", "x-sp-def", "x-speed",
    # pedras de evolução
    "fire-stone", "water-stone", "thunder-stone", "leaf-stone", "moon-stone", "sun-stone",
    "dawn-stone", "dusk-stone", "shiny-stone", "bond-ribbon",
    # incenso / boosters
    "incense", "rare-candy", "xp-booster", "iv-crystal",
    # mega stones (segeradas de mega.py) — adicionadas no fim
    *list(MEGA_FORMS.keys()),
]

# Categorias para o filtro da loja: (chave, rótulo, {categorias de item})
SHOP_CATEGORIES = [
    ("balls", "🎯 Bolas", {"ball"}),
    ("medicine", "💊 Curas", {"medicine"}),
    ("battle", "⚔️ Batalha", {"battle"}),
    ("stones", "💎 Pedras", {"stone"}),
    ("boost", "📈 Boosters", {"booster", "lure"}),
    ("mega", "🧬 Mega", {"mega-stone"}),
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


def parse_use_args(text: str) -> tuple[str, int | None, int]:
    """Separa '<item> [#pokémon] [xN]'. Retorna (nome, idx_pokémon, quantidade).

    'rare candy 5 x20' -> ('rare candy', 5, 20)
    'rare candy 5 20'  -> ('rare candy', 5, 20)
    'rare candy x20'   -> ('rare candy', None, 20)
    'thunder stone 5'  -> ('thunder stone', 5, 1)
    """
    qty = 1
    idx: int | None = None
    name_tokens: list[str] = []
    for tok in text.split():
        low = tok.lower()
        if low.startswith("x") and low[1:].isdigit():
            qty = max(1, int(low[1:]))
        elif low.endswith("x") and low[:-1].isdigit():
            qty = max(1, int(low[:-1]))
        elif tok.isdigit():
            if idx is None:
                idx = int(tok)          # 1º número = índice do pokémon
            else:
                qty = max(1, int(tok))  # 2º número = quantidade
        else:
            name_tokens.append(tok)
    return " ".join(name_tokens).strip(), idx, qty


def best_ball(owned: dict[str, int]) -> Item | None:
    """Melhor pokébola que o usuário possui (para bônus automático na captura)."""
    for key in ("masterball", "ultraball", "greatball"):
        if owned.get(key, 0) > 0:
            return ITEMS[key]
    return None
