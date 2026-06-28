"""Cartão de boas-vindas: fundo + avatar circular do novo membro + texto.

Usa o fundo de floresta embarcado (bot/assets/explore_bg.png) escurecido, com o
avatar do membro em um círculo com anel laranja no centro. Se algo falhar,
devolve None e o cog manda só o texto (nunca quebra).
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_BG_PATH = Path(__file__).resolve().parent.parent / "assets" / "explore_bg.png"
W, H = 1000, 380
AV = 168                 # diâmetro do avatar
ACCENT = (230, 126, 34)  # laranja do tema


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=max(8, size))


def _bg() -> Image.Image:
    if _BG_PATH.exists():
        img = Image.open(_BG_PATH).convert("RGBA").resize((W, H), Image.LANCZOS)
    else:
        img = Image.new("RGBA", (W, H), (22, 24, 30, 255))
    img.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 150)))  # escurece
    return img


def _compose(avatar: Image.Image | None, username: str, member_no: int | None) -> io.BytesIO:
    canvas = _bg()
    draw = ImageDraw.Draw(canvas)
    cx, cy = W // 2, 120

    # anel + avatar circular centralizado
    draw.ellipse([cx - AV // 2 - 7, cy - AV // 2 - 7, cx + AV // 2 + 7, cy + AV // 2 + 7],
                 outline=ACCENT, width=7)
    if avatar is not None:
        av = avatar.convert("RGBA").resize((AV, AV), Image.LANCZOS)
        mask = Image.new("L", (AV, AV), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, AV, AV], fill=255)
        canvas.paste(av, (cx - AV // 2, cy - AV // 2), mask)
    else:
        draw.ellipse([cx - AV // 2, cy - AV // 2, cx + AV // 2, cy + AV // 2], fill=(60, 63, 72, 255))

    def centered(text: str, y: int, font, fill) -> None:
        w = draw.textlength(text, font=font)
        # sombra leve p/ legibilidade sobre a imagem
        draw.text((cx - w / 2 + 2, y + 2), text, font=font, fill=(0, 0, 0, 180))
        draw.text((cx - w / 2, y), text, font=font, fill=fill)

    base = cy + AV // 2 + 18
    centered("BEM-VINDO(A)!", base, _font(46), (245, 246, 250))
    centered(username[:28], base + 56, _font(38), ACCENT)
    sub = f"Membro #{member_no} - use /menu para comecar!" if member_no else "Use /menu para comecar sua jornada!"
    centered(sub, H - 46, _font(22), (205, 207, 214))

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


async def render_welcome(avatar_bytes: bytes | None, username: str,
                         member_no: int | None = None) -> io.BytesIO | None:
    """Renderiza o cartão de boas-vindas. Retorna PNG (BytesIO) ou None."""
    try:
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA") if avatar_bytes else None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _compose, avatar, username, member_no)
    except Exception:  # noqa: BLE001
        return None
