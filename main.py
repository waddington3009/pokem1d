"""Ponto de entrada do PokeM1D — bot de mini-game Pokémon para Discord."""
from __future__ import annotations

import asyncio
import logging
import sys

from config import settings
from bot.core import PokeBot


class _DropStaleViewWarning(logging.Filter):
    """Descarta o aviso de clique em batalha antiga (botão sem view após restart)."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "referencing unknown view" not in record.getMessage()


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S"
    ))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    # silencia o ruído de cliques em batalhas expiradas (inofensivo)
    logging.getLogger("discord.ui.view").addFilter(_DropStaleViewWarning())


async def main() -> None:
    setup_logging()
    log = logging.getLogger("pokebot")

    if not settings.token:
        log.error(
            "DISCORD_TOKEN não definido! Copie .env.example para .env e preencha o token."
        )
        sys.exit(1)

    bot = PokeBot()
    async with bot:
        await bot.start(settings.token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nEncerrando o bot. Até logo!")
