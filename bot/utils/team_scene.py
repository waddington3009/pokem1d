"""Cena do time (p!party): cards com sprite, nome, nível e IV — líder destacado."""
from __future__ import annotations

import asyncio
import io
import math

import aiohttp
from PIL import Image, ImageDraw

from bot.utils.battle_scene import _ascii, _fetch, _font, _scaled

# layout do card
_CW, _CH = 150, 196
_GAP, _MARGIN = 12, 16
_PANEL = (46, 48, 56, 255)
_PANEL_LEAD = (58, 52, 30, 255)
_BORDER = (70, 72, 82)
_GOLD = (232, 192, 64)
_NAME = (238, 238, 242)
_SUB = (170, 172, 180)
_SHINY = (244, 206, 86)
_BG_TOP = (32, 34, 40)
_BG_BOT = (22, 24, 30)


def _iv_color(iv: float) -> tuple[int, int, int]:
    if iv >= 80:
        return (96, 210, 110)
    if iv >= 50:
        return (236, 200, 80)
    return (180, 184, 192)


def _center(draw, text, font, x, w, y, fill):
    tw = draw.textlength(text, font=font)
    draw.text((x + (w - tw) / 2, y), text, font=font, fill=fill)


def _star(draw, x, y, r, color):
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((x + rr * math.cos(ang), y + rr * math.sin(ang)))
    draw.polygon(pts, fill=color)


def _compose_team(members, sprites) -> io.BytesIO:
    n = len(members)
    cols = min(3, n)
    rows = (n + cols - 1) // cols
    W = _MARGIN * 2 + cols * _CW + (cols - 1) * _GAP
    H = _MARGIN * 2 + rows * _CH + (rows - 1) * _GAP

    canvas = Image.new("RGBA", (W, H), _BG_BOT)
    # fundo gradiente vertical sutil
    for y in range(H):
        t = y / max(1, H)
        c = tuple(int(_BG_TOP[i] + (_BG_BOT[i] - _BG_TOP[i]) * t) for i in range(3))
        ImageDraw.Draw(canvas).line([(0, y), (W, y)], fill=c)
    draw = ImageDraw.Draw(canvas)
    fname = _font(16)
    fsub = _font(13)
    fsmall = _font(12)
    flead = _font(12)

    for i, (m, sprite) in enumerate(zip(members, sprites)):
        cx = _MARGIN + (i % cols) * (_CW + _GAP)
        cy = _MARGIN + (i // cols) * (_CH + _GAP)
        lead = m["lead"]
        panel = _PANEL_LEAD if lead else _PANEL
        draw.rounded_rectangle([cx, cy, cx + _CW, cy + _CH], radius=12, fill=panel,
                               outline=(_GOLD if lead else _BORDER), width=(3 if lead else 1))
        # posição / #idx
        draw.text((cx + 10, cy + 8), f"#{m['idx']}", font=fsmall, fill=_SUB)
        if lead:
            tag = "LIDER"
            tw = draw.textlength(tag, font=flead)
            tx = cx + _CW - tw - 10
            draw.text((tx, cy + 8), tag, font=flead, fill=_GOLD)
            _star(draw, tx - 9, cy + 14, 5, _GOLD)
        # sprite
        if sprite is not None:
            s = _scaled(sprite, 92)
            canvas.alpha_composite(s, (cx + (_CW - s.width) // 2, cy + 26))
        # nome (shiny = nome em dourado, sem emoji que a fonte não tem)
        _center(draw, _ascii(m["name"]), fname, cx, _CW, cy + 124,
                _SHINY if m["shiny"] else _NAME)
        # nível
        _center(draw, f"Nv {m['level']}", fsub, cx, _CW, cy + 146, _SUB)
        # barra de IV
        iv = m["iv"]
        bx, by, bw, bh = cx + 18, cy + 170, _CW - 36, 8
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=4, fill=(70, 72, 82))
        fillw = int(bw * max(0.0, min(1.0, iv / 100)))
        if fillw > 0:
            draw.rounded_rectangle([bx, by, bx + fillw, by + bh], radius=4, fill=_iv_color(iv))
        _center(draw, f"IV {iv:.0f}%", fsmall, cx, _CW, cy + 178, _SUB)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


async def render_team(members: list[dict]) -> io.BytesIO | None:
    """members: lista de dicts {species_id, shiny, name, level, iv, idx, lead}."""
    if not members:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            sprites = await asyncio.gather(
                *(_fetch(session, m["species_id"], m["shiny"], False) for m in members))
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _compose_team, members, list(sprites))
    except Exception:  # noqa: BLE001
        return None
