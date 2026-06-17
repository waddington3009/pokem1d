"""Cartão visual da Home do /menu.

Usa a arte de fundo embarcada (bot/assets/menu_home.png) e escreve por cima os
valores do jogador (PokéCoins, Time, Líder, Coleção, Pokédex, Insígnias) e cola
a arte do pokémon líder no quadro da direita.

Tudo em frações da imagem (independe da resolução do PNG exportado). Se a imagem
de fundo não existir ou algo falhar, devolve None e a Home cai no visual de texto
antigo (nunca quebra).

Calibração: ligue DEBUG=True para desenhar cruzes vermelhas nas âncoras e o
retângulo do quadro do líder — tire um print e ajuste COORDS/FRAME.
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageFont

from config import settings

_BG_PATH = Path(__file__).resolve().parent.parent / "assets" / "menu_home.png"
_BG_CACHE: Image.Image | None = None
_SPRITE_CACHE: dict[tuple[int, bool], Image.Image | None] = {}

DEBUG = False  # True = desenha guias de calibração

# Âncora de cada valor: (x, y) em FRAÇÃO da imagem. O texto é desenhado
# alinhado à ESQUERDA e centralizado verticalmente nesse ponto (logo após o rótulo).
COORDS: dict[str, tuple[float, float]] = {
    "coins":     (0.229, 0.345),
    "time":      (0.183, 0.496),
    "lider":     (0.449, 0.496),
    "colecao":   (0.212, 0.657),
    "pokedex":   (0.478, 0.657),
    "insignias": (0.215, 0.814),
}
# Quadro do líder (x0, y0, x1, y1) em fração — onde a arte do pokémon é colada.
FRAME: tuple[float, float, float, float] = (0.615, 0.10, 0.965, 0.855)

VALUE_SIZE_FRAC = 0.042       # altura da fonte dos valores (fração da altura)
VALUE_COLOR = (240, 241, 245)
SPRITE_PAD = 0.86             # quanto da caixa o sprite ocupa (margem de respiro)


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=max(8, size))


def _bg() -> Image.Image | None:
    global _BG_CACHE
    if _BG_CACHE is None:
        if not _BG_PATH.exists():
            return None
        _BG_CACHE = Image.open(_BG_PATH).convert("RGBA")
    return _BG_CACHE.copy()


async def _fetch_art(species_id: int, shiny: bool) -> Image.Image | None:
    key = (species_id, shiny)
    if key in _SPRITE_CACHE:
        return _SPRITE_CACHE[key]
    url = settings.sprite(species_id, shiny=shiny, official=True)  # arte oficial (alta res)
    img: Image.Image | None = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    img = Image.open(io.BytesIO(await resp.read())).convert("RGBA")
    except Exception:  # noqa: BLE001
        img = None
    _SPRITE_CACHE[key] = img
    return img


def _fit(sprite: Image.Image, box_w: int, box_h: int) -> Image.Image:
    scale = min(box_w / sprite.width, box_h / sprite.height) * SPRITE_PAD
    w, h = max(1, int(sprite.width * scale)), max(1, int(sprite.height * scale))
    return sprite.resize((w, h), Image.LANCZOS)


def _compose(values: dict[str, str], art: Image.Image | None) -> io.BytesIO | None:
    canvas = _bg()
    if canvas is None:
        return None
    W, H = canvas.size
    draw = ImageDraw.Draw(canvas)
    font = _font(int(H * VALUE_SIZE_FRAC))

    # cola a arte do líder no quadro
    if art is not None:
        x0, y0, x1, y1 = (int(FRAME[0] * W), int(FRAME[1] * H), int(FRAME[2] * W), int(FRAME[3] * H))
        s = _fit(art, x1 - x0, y1 - y0)
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        canvas.alpha_composite(s, (cx - s.width // 2, cy - s.height // 2))

    # escreve os valores
    for key, text in values.items():
        if key not in COORDS or not text:
            continue
        fx, fy = COORDS[key]
        x, y = int(fx * W), int(fy * H)
        asc, desc = font.getmetrics()
        draw.text((x, y - (asc + desc) // 2), text, font=font, fill=VALUE_COLOR)

    if DEBUG:
        for fx, fy in COORDS.values():
            x, y = int(fx * W), int(fy * H)
            draw.line([(x - 14, y), (x + 14, y)], fill=(255, 60, 60), width=2)
            draw.line([(x, y - 14), (x, y + 14)], fill=(255, 60, 60), width=2)
        fx0, fy0, fx1, fy1 = FRAME
        draw.rectangle([int(fx0 * W), int(fy0 * H), int(fx1 * W), int(fy1 * H)],
                       outline=(255, 60, 60), width=3)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


async def render_home_card(*, coins: int, slots: int, leader: str, leader_id: int,
                           leader_shiny: bool, collection: int, dex: int, dex_total: int,
                           badges: int) -> io.BytesIO | None:
    """Renderiza o cartão da Home. Retorna PNG (BytesIO) ou None (usa fallback de texto)."""
    if not _BG_PATH.exists():
        return None
    try:
        art = await _fetch_art(leader_id, leader_shiny) if leader_id else None
        values = {
            "coins": f"{coins:,}".replace(",", "."),
            "time": f"{slots} slots",
            "lider": leader,
            "colecao": str(collection),
            "pokedex": f"{dex}/{dex_total}",
            "insignias": str(badges),
        }
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _compose, values, art)
    except Exception:  # noqa: BLE001
        return None
