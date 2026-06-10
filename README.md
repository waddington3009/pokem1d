# 🔴 PokeM1D — Bot de Mini-Game Pokémon para Discord

Capture, evolua, batalhe, troque e colecione Pokémon direto no seu servidor do Discord.
Inspirado em bots como Pokétwo/PokéMeow, construído em **Python + discord.py + SQLAlchemy (async)**.

---

## ✨ Funcionalidades

| Sistema | Comandos principais |
|---------|--------------------|
| 🧭 **Exploração** | `explore` → encontro com **Capturar / Batalhar / Ignorar** |
| 🥚 **Spawn** | aparição automática por mensagens + `forcespawn` (owner) |
| 🎯 **Captura** | `catch <nome>` (spawns) ou botão **Capturar** (exploração) |
| 📕 **Coleção** | `pokemon`, `pokedex`, `info`, `select`, `favorite`, `nickname`, `release` |
| 📊 **Stats** | IVs (0–31), naturezas, níveis/XP, cálculo de atributos |
| 🔄 **Evolução** | `evolve` (nível) e `use <pedra>` (pedra), com confirmação |
| ⚔️ **Batalha** | `battle @user` (PvP), `duel` (PvE), por turnos com botões |
| 💰 **Economia** | `balance`, `daily`, `shop`, `buy`, `sell`, `market` |
| 🤝 **Trocas** | `trade @user`, `trade add/coins/confirm/cancel` |
| 🎁 **Itens** | `bag`, `use` (pokébolas, pedras, incenso, boosters) |
| 🏆 **Progressão** | `profile`, `leaderboard`, `quests`, `achievements` |
| ⚙️ **Admin** | `config`, `setprefix`, `redirect`, `blacklist`, `togglespawns` |

---

## 🚀 Instalação rápida

```bash
# 1. Dependências
pip install -r requirements.txt

# 2. Configuração
copy .env.example .env        # Windows  (cp no Linux/Mac)
#  -> edite .env e cole o DISCORD_TOKEN

# 3. (Opcional) Expandir a Pokédex via PokéAPI
python scripts/build_dataset.py 1 386     # Gens 1-3

# 4. Rodar
python main.py
```

### Pré-requisitos no Discord Developer Portal
1. Crie uma aplicação → **Bot** → copie o **Token** para o `.env`.
2. Em **Privileged Gateway Intents**, ative **MESSAGE CONTENT INTENT** e **SERVER MEMBERS INTENT**.
3. Convide o bot com escopo `bot` e permissões: *Send Messages, Embed Links, Read Message History, Add Reactions*.

Primeiro comando no servidor: **`p!start`** para ganhar seu pokémon inicial.

---

## 🗂️ Arquitetura

```
PokeM1D/
├── main.py                  # ponto de entrada (asyncio)
├── config.py                # settings via .env (token, db, parâmetros de jogo)
├── data/
│   └── pokemon.json         # dataset de espécies (seed: Kanto)
├── scripts/
│   └── build_dataset.py     # expande o dataset pela PokéAPI
└── bot/
    ├── core.py              # subclasse do bot (prefixo dinâmico, carga de cogs)
    ├── database/
    │   ├── models.py        # User, Pokemon, PokedexEntry, Inventory, Market, Guild
    │   └── db.py            # engine async + helpers get-or-create
    ├── data/
    │   ├── pokemon_data.py  # loader + índice de nomes (POKEDEX)
    │   ├── moves.py         # golpes
    │   ├── types.py         # tabela de tipos (18×18)
    │   ├── natures.py       # 25 naturezas
    │   └── items.py         # pokébolas, pedras, boosters, incenso
    ├── game/
    │   └── battle_engine.py # motor de batalha (desacoplado do Discord)
    ├── utils/
    │   ├── stats.py         # IVs, cálculo de atributos, XP/níveis
    │   ├── rarity.py        # pesos de spawn, shiny, recompensas
    │   ├── embeds.py        # cartões visuais
    │   ├── helpers.py       # acesso a dados compartilhado
    │   ├── progression.py   # missões e conquistas
    │   ├── paginator.py     # navegação com botões
    │   └── confirm.py       # view de confirmação
    └── cogs/                # um arquivo por sistema
        ├── admin.py  spawning.py  catching.py  pokedex.py  evolution.py
        ├── battle.py economy.py   items.py     trading.py  progression.py
        └── general.py
```

### Como funciona o spawn
A cada mensagem em um canal, um contador aumenta. Ao atingir um limiar aleatório
(`spawn_min_messages`–`spawn_max_messages`), um pokémon aparece — ponderado por
raridade. Ele some após `spawn_despawn_seconds`. O incenso reduz o limiar pela metade.

---

## 🛠️ Configuração de jogo
Ajuste os parâmetros em [`config.py`](config.py) (`Settings`): frequência de spawn,
chance de shiny (1/4000), recompensas, streak diário, URLs de sprites e cores.

---

## 🖥️ Deploy em VPS

**SQLite (simples):** funciona out-of-the-box; o arquivo `pokebot.db` é criado sozinho.

**PostgreSQL (recomendado para produção):**
```bash
pip install asyncpg
# no .env:
DATABASE_URL=postgresql+asyncpg://user:senha@localhost:5432/pokebot
```

**Manter rodando 24/7 (systemd):**
```ini
# /etc/systemd/system/pokem1d.service
[Unit]
Description=PokeM1D Discord Bot
After=network.target

[Service]
WorkingDirectory=/opt/PokeM1D
ExecStart=/opt/PokeM1D/venv/bin/python main.py
Restart=always
User=pokebot

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now pokem1d
sudo journalctl -u pokem1d -f      # logs
```

> Para escala maior, considere **Redis** para spawns/cooldowns e mover o estado de
> trocas/batalhas (hoje em memória) para um store compartilhado.

---

## 📋 Lista de comandos (prefixo padrão `p!`)

<details>
<summary><b>Exploração & Captura</b></summary>

- `explore` — explora a região; pode achar nada, moedas ou um pokémon
  - No encontro: **🎯 Capturar** (chance por raridade), **⚔️ Batalhar** (vença = captura garantida), **🏃 Ignorar**
- `catch <nome>` — captura o pokémon selvagem dos spawns automáticos
- `pokemon [filtros]` — sua coleção (`shiny`, `fav`, `legendary`, `name:x`, `--iv`, `--level`)
- `pokedex` — progresso da Pokédex
- `info [#|latest]` — detalhes de um pokémon
- `select <#>` • `favorite <#>` • `unfavorite <#>` • `nickname <#> <nome>` • `release <#>`
- `species <nome>` — consulta dados de uma espécie
</details>

<details>
<summary><b>Economia, Itens & Mercado</b></summary>

- `balance` • `daily` • `shop` • `buy <item> [qtd]` • `sell <item> [qtd]`
- `bag` • `use <item> [#]`
- `market` • `market add <#> <preço>` • `market buy <id>` • `market remove <id>`
</details>

<details>
<summary><b>Evolução, Batalha & Troca</b></summary>

- `evolve [#]` • `use <pedra> <#>`
- `duel` (PvE) • `battle @user` (PvP)
- `trade @user` • `trade add <#>` • `trade coins <n>` • `trade confirm` • `trade cancel`
</details>

<details>
<summary><b>Progressão & Admin</b></summary>

- `profile [@user]` • `leaderboard <tipo>` • `quests` • `achievements`
- `config` • `setprefix <p>` • `redirect [#canal]` • `blacklist <add|remove> [#canal]` • `togglespawns`
</details>

---

## 📜 Licença
Projeto educacional. Pokémon é marca registrada da Nintendo/Game Freak/The Pokémon Company.
Sprites servidos via [PokéAPI](https://pokeapi.co/).
