"""Compõe a 'cena' de batalha estilo Pokémon (fundo + 2 sprites + barras de HP).

Monta uma única imagem PNG por turno, no estilo do Pokétwo:
  - fundo de campo (céu + grama + plataformas) desenhado na hora;
  - sprite do OPONENTE de frente (em cima) e o SEU de costas (embaixo);
  - caixas de HP no estilo do jogo, com nome, nível, barra colorida e
    as poké bolas do time (vivas/desmaiadas).

Tudo é cacheado em memória; se algo falhar, devolve None e a batalha
continua com o visual antigo (nunca quebra a batalha).
"""
from __future__ import annotations

import asyncio
import io

import aiohttp
from PIL import Image, ImageDraw, ImageFont

# cache de sprites já baixados: (species_id, shiny, back) -> PIL.Image | None
_SPRITE_CACHE: dict[tuple[int, bool, bool], Image.Image | None] = {}

_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/"

# ---- dimensões da cena ----
W, H = 480, 260

# cores (paleta suave — brilho reduzido para não cansar a vista)
_SKY_TOP = (120, 165, 195)
_SKY_BOT = (158, 188, 205)
_GRASS = (96, 158, 96)
_PLAT = (80, 140, 80)
_PLAT_EDGE = (64, 116, 64)
_BOX_BG = (228, 228, 222)
_BOX_EDGE = (60, 60, 70)
_TXT = (40, 42, 52)
_HP_BACK = (90, 92, 100)


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def _sprite_url(species_id: int, shiny: bool, back: bool) -> str:
    sub = ""
    if back:
        sub += "back/"
    if shiny:
        sub += "shiny/"
    return f"{_BASE}{sub}{species_id}.png"


async def _fetch(session: aiohttp.ClientSession, species_id: int, shiny: bool, back: bool):
    key = (species_id, shiny, back)
    if key in _SPRITE_CACHE:
        return _SPRITE_CACHE[key]
    img: Image.Image | None = None
    # tenta o sprite pedido; se for 'costas' e não existir, cai para o de frente
    for try_back in ([back, False] if back else [False]):
        url = _sprite_url(species_id, shiny, try_back)
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    data = await r.read()
                    img = Image.open(io.BytesIO(data)).convert("RGBA")
                    break
        except Exception:  # noqa: BLE001
            img = None
    _SPRITE_CACHE[key] = img
    return img


def _hp_color(frac: float) -> tuple[int, int, int]:
    if frac > 0.5:
        return (88, 200, 96)
    if frac > 0.2:
        return (240, 200, 64)
    return (224, 80, 72)


def _trim(img: Image.Image) -> Image.Image:
    """Recorta o espaço transparente em volta do sprite."""
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def _scaled(img: Image.Image, target_h: int) -> Image.Image:
    img = _trim(img)
    scale = target_h / max(1, img.height)
    return img.resize((max(1, int(img.width * scale)), target_h), Image.NEAREST)


def _draw_background(draw: ImageDraw.ImageDraw, canvas: Image.Image) -> None:
    # céu (gradiente vertical) na metade de cima
    horizon = 150
    for y in range(horizon):
        t = y / horizon
        r = int(_SKY_TOP[0] + (_SKY_BOT[0] - _SKY_TOP[0]) * t)
        g = int(_SKY_TOP[1] + (_SKY_BOT[1] - _SKY_TOP[1]) * t)
        b = int(_SKY_TOP[2] + (_SKY_BOT[2] - _SKY_TOP[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    # grama
    draw.rectangle([0, horizon, W, H], fill=_GRASS)
    # plataforma do oponente (em cima/direita)
    draw.ellipse([280, 118, 460, 158], fill=_PLAT, outline=_PLAT_EDGE, width=3)
    # plataforma do jogador (embaixo/esquerda)
    draw.ellipse([10, 206, 240, 254], fill=_PLAT, outline=_PLAT_EDGE, width=3)


def _draw_team_balls(draw: ImageDraw.ImageDraw, x: int, y: int, alive: int, total: int) -> None:
    for i in range(total):
        cx = x + i * 16
        if i < alive:
            draw.ellipse([cx, y, cx + 11, y + 11], fill=(224, 64, 56), outline=(40, 40, 40))
            draw.line([(cx, y + 5), (cx + 11, y + 5)], fill=(40, 40, 40))
        else:
            draw.ellipse([cx, y, cx + 11, y + 11], fill=(150, 150, 156), outline=(90, 90, 96))


def _draw_hp_box(draw: ImageDraw.ImageDraw, x: int, y: int, w: int,
                 name: str, level: int, frac: float, alive: int, total: int,
                 shiny: bool, show_numbers: bool, cur: int, mx: int) -> None:
    h = 58
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=_BOX_BG, outline=_BOX_EDGE, width=2)
    fname = _font(15)
    fsub = _font(11)
    nm = ("✨ " if shiny else "") + name
    draw.text((x + 10, y + 6), nm, font=fname, fill=_TXT)
    lv = f"Nv{level}"
    lvw = draw.textlength(lv, font=fsub)
    draw.text((x + w - lvw - 10, y + 9), lv, font=fsub, fill=_TXT)
    # barra de HP
    bx, by, bw, bh = x + 10, y + 27, w - 20, 9
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=4, fill=_HP_BACK)
    fillw = int(bw * max(0.0, min(1.0, frac)))
    if fillw > 0:
        draw.rounded_rectangle([bx, by, bx + fillw, by + bh], radius=4, fill=_hp_color(frac))
    # base: números de HP (esquerda, só do jogador) + bolas do time (direita)
    if show_numbers:
        draw.text((x + 10, y + 41), f"{cur}/{mx} HP", font=fsub, fill=_TXT)
    _draw_team_balls(draw, x + w - total * 16 - 4, y + 42, alive, total)


def _compose(p1_sprite, p2_sprite, p1, p2, p1_alive, p2_alive, p1_total, p2_total) -> io.BytesIO:
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    _draw_background(draw, canvas)

    # oponente (frente), em pé sobre a plataforma de cima
    if p2_sprite is not None:
        s = _scaled(p2_sprite, 96)
        px = 370 - s.width // 2
        py = 138 - s.height
        canvas.alpha_composite(s, (px, max(0, py)))
    # jogador (costas), maior, sobre a plataforma de baixo
    if p1_sprite is not None:
        s = _scaled(p1_sprite, 110)
        px = 110 - s.width // 2
        py = 232 - s.height
        canvas.alpha_composite(s, (px, max(0, py)))

    # caixa de HP do oponente (cima/esquerda) — sem números
    _draw_hp_box(draw, 16, 16, 200, p2.name, p2.level, p2.hp_fraction(),
                 p2_alive, p2_total, p2.shiny, show_numbers=False, cur=p2.hp, mx=p2.max_hp)
    # caixa de HP do jogador (baixo/direita) — com números
    _draw_hp_box(draw, 264, 176, 200, p1.name, p1.level, p1.hp_fraction(),
                 p1_alive, p1_total, p1.shiny, show_numbers=True, cur=p1.hp, mx=p1.max_hp)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


async def render_battle_scene(p1, p2, p1_team, p2_team) -> io.BytesIO | None:
    """Gera o PNG da cena. p1 = ativo do jogador (costas), p2 = ativo do oponente (frente).

    Retorna BytesIO pronto para anexo, ou None se algo falhar.
    """
    try:
        async with aiohttp.ClientSession() as session:
            p1_sprite, p2_sprite = await asyncio.gather(
                _fetch(session, p1.species.id, p1.shiny, back=True),
                _fetch(session, p2.species.id, p2.shiny, back=False),
            )
        p1_alive = sum(1 for m in p1_team if m.alive)
        p2_alive = sum(1 for m in p2_team if m.alive)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _compose, p1_sprite, p2_sprite, p1, p2,
            p1_alive, p2_alive, len(p1_team), len(p2_team),
        )
    except Exception:  # noqa: BLE001
        return None
