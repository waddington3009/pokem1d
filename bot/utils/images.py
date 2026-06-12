"""Geração da grade visual da coleção (sprites + nomes) com Pillow.

Baixa os sprites estáticos (com cache em memória), compõe uma grade e devolve
um PNG pronto para enviar como anexo no Discord.
"""
from __future__ import annotations

import asyncio
import io

import aiohttp
from PIL import Image, ImageDraw, ImageFont

from config import settings

# cache de sprites já baixados: (species_id, shiny) -> PIL.Image (RGBA)
_SPRITE_CACHE: dict[tuple[int, bool], Image.Image | None] = {}

# layout
_CELL_W, _CELL_H = 124, 150
_SPRITE = 96
_BG = (43, 45, 49, 255)       # cinza do tema escuro do Discord
_NAME = (236, 236, 240)
_SUB = (160, 162, 170)
_SHINY = (255, 205, 40)


def _font(size: int) -> ImageFont.FreeTypeFont:
    # Pillow >= 10.1: load_default(size) devolve uma fonte TrueType escalável
    return ImageFont.load_default(size=size)


async def _fetch_sprite(session: aiohttp.ClientSession, species_id: int, shiny: bool):
    key = (species_id, shiny)
    if key in _SPRITE_CACHE:
        return _SPRITE_CACHE[key]
    url = settings.sprite(species_id, shiny=shiny)  # sprite estático (96x96)
    img: Image.Image | None = None
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                data = await resp.read()
                img = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:  # noqa: BLE001
        img = None
    _SPRITE_CACHE[key] = img
    return img


def _truncate(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def _compose(sprites, labels, cols: int) -> io.BytesIO:
    n = len(sprites)
    rows = (n + cols - 1) // cols
    canvas = Image.new("RGBA", (cols * _CELL_W, rows * _CELL_H), _BG)
    draw = ImageDraw.Draw(canvas)
    fname = _font(14)
    fsub = _font(12)

    for i, (sprite, (name, sub, shiny)) in enumerate(zip(sprites, labels)):
        cx = (i % cols) * _CELL_W
        cy = (i // cols) * _CELL_H
        if sprite is not None:
            s = sprite.resize((_SPRITE, _SPRITE))
            canvas.paste(s, (cx + (_CELL_W - _SPRITE) // 2, cy + 6), s)
        # nome (centralizado)
        nm = _truncate(draw, name, fname, _CELL_W - 8)
        nw = draw.textlength(nm, font=fname)
        draw.text((cx + (_CELL_W - nw) / 2, cy + 104), nm,
                  font=fname, fill=(_SHINY if shiny else _NAME))
        # subtítulo (#idx • Nv)
        sw = draw.textlength(sub, font=fsub)
        draw.text((cx + (_CELL_W - sw) / 2, cy + 124), sub, font=fsub, fill=_SUB)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


async def render_grid(entries: list[tuple[int, bool, str, str]], cols: int = 3) -> io.BytesIO:
    """entries: lista de (species_id, shiny, nome, subtitulo). Retorna PNG (BytesIO)."""
    async with aiohttp.ClientSession() as session:
        sprites = await asyncio.gather(
            *(_fetch_sprite(session, e[0], e[1]) for e in entries)
        )
    labels = [(e[2], e[3], e[1]) for e in entries]
    loop = asyncio.get_running_loop()
    # compõe a imagem fora do event loop (Pillow é CPU-bound)
    return await loop.run_in_executor(None, _compose, list(sprites), labels, cols)
