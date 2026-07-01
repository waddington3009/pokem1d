"""Cartão de imagem da Pesquisa de Campo: uma barra de progresso até a Caçada.

Desenhado com Pillow (sem depender de asset externo). Estilo escuro + laranja,
combinando com o cartão da Home. Se algo falhar, devolve None (a tela cai no texto).
"""
from __future__ import annotations

import asyncio
import io

from PIL import Image, ImageDraw, ImageFont

W, H = 900, 240
BG = (24, 26, 32, 255)
PANEL = (32, 35, 43, 255)
TRACK = (48, 51, 60, 255)
ACCENT = (230, 126, 34)
ACCENT2 = (241, 196, 15)
TEXT = (240, 241, 245)
SUB = (170, 173, 182)


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=max(8, size))


def _compose(points: int, cost: int, frac: float, ready: bool) -> io.BytesIO:
    frac = max(0.0, min(1.0, frac))
    canvas = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(canvas)
    # painel arredondado
    draw.rounded_rectangle([16, 16, W - 16, H - 16], radius=22, fill=PANEL,
                           outline=ACCENT, width=3)

    draw.text((44, 40), "PESQUISA DE CAMPO", font=_font(34), fill=TEXT)
    draw.text((46, 82), "Progresso ate a Cacada Lendaria", font=_font(20), fill=SUB)

    # trilha da barra
    bx0, by0, bx1, by1 = 46, 128, W - 46, 172
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=22, fill=TRACK)
    # preenchimento
    fill_w = int((bx1 - bx0) * frac)
    if fill_w > 8:
        for i in range(fill_w):   # leve degradê laranja->amarelo
            t = i / max(1, bx1 - bx0)
            col = tuple(int(ACCENT[j] + (ACCENT2[j] - ACCENT[j]) * t) for j in range(3))
            draw.line([(bx0 + i, by0), (bx0 + i, by1)], fill=col)
        # arredonda as pontas cobrindo cantos
        draw.rounded_rectangle([bx0, by0, bx0 + min(fill_w, bx1 - bx0), by1], radius=22,
                               outline=None, width=0, fill=None)

    pct = int(frac * 100)
    draw.text((bx0 + 6, by0 + 10), f"{points:,} / {cost:,}", font=_font(22), fill=(20, 20, 22))
    ptxt = f"{pct}%"
    pw = draw.textlength(ptxt, font=_font(22))
    draw.text((bx1 - pw - 8, by0 + 10), ptxt, font=_font(22), fill=(20, 20, 22))

    footer = ("CACADA LENDARIA LIBERADA! Clique em Iniciar Cacada." if ready
              else f"Faltam {max(0, cost - points):,} pontos para a Cacada.")
    draw.text((46, 190), footer, font=_font(20), fill=(ACCENT2 if ready else SUB))

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


async def render_research_card(points: int, cost: int, frac: float, ready: bool) -> io.BytesIO | None:
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _compose, points, cost, frac, ready)
    except Exception:  # noqa: BLE001
        return None
