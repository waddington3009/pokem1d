"""Cenas do p!explore: fundo de floresta + pokémon / tesouro / nada.

Usa uma imagem de fundo embarcada (bot/assets/explore_bg.png) e compõe:
  - encontro: o pokémon (de frente) em pé na trilha, com sombra e brilho de raridade;
  - tesouro: uma pilha de moedas douradas com brilho;
  - nada: apenas o fundo (levemente escurecido).

Se algo falhar, devolve None e o explore usa o visual antigo (nunca quebra).
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageFilter

from bot.utils.battle_scene import _fetch, _scaled
from bot.utils.rarity import RARITY_COLOR

W, H = 480, 270
_BG_PATH = Path(__file__).resolve().parent.parent / "assets" / "explore_bg.png"
_BG_CACHE: Image.Image | None = None


def _bg() -> Image.Image:
    """Carrega (e cacheia) o fundo já redimensionado para a cena."""
    global _BG_CACHE
    if _BG_CACHE is None:
        img = Image.open(_BG_PATH).convert("RGBA").resize((W, H), Image.LANCZOS)
        _BG_CACHE = img
    return _BG_CACHE.copy()


def _darken(canvas: Image.Image, alpha: int) -> None:
    canvas.alpha_composite(Image.new("RGBA", canvas.size, (0, 0, 0, alpha)))


def _ground_shadow(canvas: Image.Image, cx: int, cy: int, w: int) -> None:
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    d.ellipse([cx - w // 2, cy - w // 6, cx + w // 2, cy + w // 6], fill=(0, 0, 0, 110))
    sh = sh.filter(ImageFilter.GaussianBlur(5))
    canvas.alpha_composite(sh)


def _glow(canvas: Image.Image, cx: int, cy: int, color: tuple[int, int, int], r: int) -> None:
    g = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    for i in range(4):
        rr = r - i * (r // 5)
        a = 26 + i * 14
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(*color, a))
    g = g.filter(ImageFilter.GaussianBlur(8))
    canvas.alpha_composite(g)


def _sparkle(draw: ImageDraw.ImageDraw, x: int, y: int, s: int,
             color: tuple[int, int, int] = (255, 255, 255)) -> None:
    draw.polygon(
        [(x, y - s), (x + s * 0.28, y - s * 0.28), (x + s, y), (x + s * 0.28, y + s * 0.28),
         (x, y + s), (x - s * 0.28, y + s * 0.28), (x - s, y), (x - s * 0.28, y - s * 0.28)],
        fill=color)


def _draw_coin(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    # moeda em perspectiva (elipse) dourada, com borda e brilho
    draw.ellipse([cx - r, cy - int(r * 0.72), cx + r, cy + int(r * 0.72)],
                 fill=(238, 196, 56), outline=(170, 128, 20), width=2)
    draw.ellipse([cx - int(r * 0.62), cy - int(r * 0.44), cx + int(r * 0.62), cy + int(r * 0.44)],
                 outline=(255, 226, 120), width=2)
    draw.ellipse([cx - int(r * 0.5), cy - int(r * 0.36), cx - int(r * 0.05), cy - int(r * 0.02)],
                 fill=(255, 240, 170))


# --------------------------------------------------------------------------
def _compose_pokemon(sprite, rarity: str, shiny: bool) -> io.BytesIO:
    canvas = _bg()
    _darken(canvas, 40)
    cx, ground = W // 2, 232
    # brilho de raridade (só para raros+)
    if rarity in ("rare", "superrare", "legendary", "mythical"):
        color = tuple(((RARITY_COLOR.get(rarity, 0xFFFFFF) >> s) & 0xFF) for s in (16, 8, 0))
        _glow(canvas, cx, ground - 60, color, 150)
    _ground_shadow(canvas, cx, ground, 150)
    if sprite is not None:
        s = _scaled(sprite, 150)
        canvas.alpha_composite(s, (cx - s.width // 2, ground - s.height))
    if shiny:
        draw = ImageDraw.Draw(canvas)
        for (sx, sy, ss) in [(cx + 70, ground - 150, 9), (cx - 80, ground - 110, 7),
                             (cx + 95, ground - 80, 6)]:
            _sparkle(draw, sx, sy, ss, (255, 244, 170))
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


def _compose_coins() -> io.BytesIO:
    canvas = _bg()
    _darken(canvas, 70)
    cx, cy = W // 2, H // 2 + 26
    _glow(canvas, cx, cy, (255, 210, 70), 150)
    draw = ImageDraw.Draw(canvas)
    # pilha de moedas (de trás para frente)
    pile = [(cx - 34, cy + 18), (cx + 34, cy + 18), (cx, cy + 22),
            (cx - 17, cy - 4), (cx + 17, cy - 4), (cx, cy - 26)]
    for mx, my in pile:
        _draw_coin(draw, mx, my, 28)
    for (sx, sy, ss) in [(cx - 70, cy - 50, 10), (cx + 74, cy - 40, 8), (cx + 30, cy - 70, 7)]:
        _sparkle(draw, sx, sy, ss, (255, 248, 200))
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


def _compose_nothing() -> io.BytesIO:
    canvas = _bg()
    _darken(canvas, 90)
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# --------------------------------------------------------------------------
async def render_explore_scene(kind: str, species=None, shiny: bool = False) -> io.BytesIO | None:
    """kind: 'pokemon' | 'coins' | 'nothing'. Retorna PNG (BytesIO) ou None."""
    try:
        loop = asyncio.get_running_loop()
        if kind == "pokemon" and species is not None:
            async with aiohttp.ClientSession() as session:
                sprite = await _fetch(session, species.id, shiny, back=False)
            return await loop.run_in_executor(None, _compose_pokemon, sprite, species.rarity, shiny)
        if kind == "coins":
            return await loop.run_in_executor(None, _compose_coins)
        return await loop.run_in_executor(None, _compose_nothing)
    except Exception:  # noqa: BLE001
        return None
