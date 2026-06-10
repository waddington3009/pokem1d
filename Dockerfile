# ---- PokeM1D :: imagem de produção ----
FROM python:3.13-slim AS base

# Python otimizado para container
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) Dependências primeiro (cache de layer — só reinstala se requirements mudar).
#    asyncpg/discord.py/sqlalchemy têm wheels prontas; não precisa de compilador.
COPY requirements.txt .
RUN pip install -r requirements.txt

# 2) Código da aplicação
COPY . .

# 3) Usuário não-root (boa prática de segurança)
RUN useradd --create-home --uid 10001 botuser \
    && chown -R botuser:botuser /app
USER botuser

# Discord bot = só conexões de saída; nenhuma porta precisa ser exposta.
CMD ["python", "main.py"]
