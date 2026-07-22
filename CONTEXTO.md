# CONTEXTO — PokeM1D (handoff completo)

> Documento de contexto do bot. Serve pra retomar o projeto em qualquer PC e pra
> qualquer pessoa (ou IA) entender tudo. Atualize quando mudar algo grande.

---

## 1. O que é
**PokeM1D** — bot de Discord de mini-game Pokémon (capturar, evoluir, batalhar,
trocar, colecionar, subir de nível). Escrito em **Python 3.13 + discord.py 2.x**,
com **SQLAlchemy async**. Quase tudo é jogado por **`/menu`** (painel privado com
botões); comandos por prefixo `p!` ficaram só para **admins/dono** e uns poucos
públicos.

- **Repositório:** https://github.com/waddington3009/pokem1d
- **Bot:** PokeM1D#5146 · **Application/Client ID:** 1514070511729250334
- **Dono/dev:** waddington (waddington2415@gmail.com)

---

## 2. Deploy / Produção
- Roda numa **VPS EasyPanel**.
- O bot é um **serviço Docker linkado ao GitHub**: **deploy acontece por `git push`**
  na branch `main` → o EasyPanel rebuilda o container.
- O **banco é um serviço Postgres separado** (não usa o SQLite local).
- **Não pushar sem necessidade** — todo push vai pra produção.
- Slash commands: o bot **sincroniza sozinho** no `on_ready` (1x por processo) e no
  **`on_guild_join`** (quando entra em servidor novo). Sync por servidor é instantâneo.
  Se algum `/` não aparecer, rode **`p!sync`** (dono) ou reinicie o serviço.

### Fluxo de trabalho
1. Editar código localmente.
2. Testar (imports/sintaxe; ver seção 9).
3. `git add ... && git commit` → `git push origin main` (dispara deploy).

---

## 3. Rodar em outro PC (setup do zero)
```bash
git clone https://github.com/waddington3009/pokem1d
cd pokem1d
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env                               # e preencha o .env
python main.py
```
- **`.env`** (NUNCA versionar) precisa de: `DISCORD_TOKEN`, `DATABASE_URL`,
  `OWNER_IDS`, `DEFAULT_PREFIX` (p!), `DEFAULT_LANGUAGE` (pt).
  - Dev/local: `DATABASE_URL=sqlite+aiosqlite:///pokebot.db` (cria um SQLite local).
  - Produção: `postgresql+asyncpg://user:senha@host:5432/pokebot`.
- **Token e credenciais** ficam no Discord Developer Portal e no `.env` da VPS — não
  estão no repositório.
- Privileged Intents no Developer Portal: **Message Content** e **Server Members**
  precisam estar LIGADOS (se estiverem off, o bot nem sobe).

**Ambiente:** Windows 11, Python 3.13. Shell: PowerShell (e Git Bash disponível).

---

## 4. Arquitetura / estrutura
Entrada: `main.py` → `bot/core.py` (classe `PokeBot`, carrega cogs, checks globais).

```
config.py                 # TODAS as constantes de jogo (tunáveis) + settings do .env
data/pokemon.json         # dataset das espécies (651 + Sylveon #700). Gen 1-5 + extras.
bot/
  core.py                 # PokeBot: prefixo dinâmico, EXTENSIONS, checks, on_ready/on_guild_join
  cogs/                   # 1 arquivo por área (ver abaixo)
  data/                   # dados estáticos: items, moves, natures, types, gyms, titles, pokemon_data
  database/
    models.py             # modelos SQLAlchemy: User, Pokemon, Guild, PokedexEntry, MarketListing
    db.py                 # engine, session_scope, get_or_create_*, _auto_migrate (!)
  game/battle_engine.py   # motor de batalha (BattleMon, dano, status, estágios, PP)
  utils/                  # helpers, embeds, imagens (Pillow), progressão, rarity, research, titles...
  assets/                 # imagens locais: explore_bg.png, menu_home.png
docs/                     # PLANOS futuros (não implementado): itens_batalha.md, explore_rework.md
```

### Cogs (bot/cogs/) — o que cada um faz
- **hub.py** — o `/menu` (HubView). É o CORAÇÃO do jogo. Telas: Home, Coleção
  (+filtros), detalhe do pokémon, Evoluir, Loja, Mochila (usar item), Market,
  Missões, Liga, Ranking, Perfil, Pokédex, **Pesquisa/Caçada**, Explorar. Modais de
  compra/uso com quantidade livre. Trava de "1 /menu aberto por usuário" (anti-bypass
  de cooldown). Comandos: `/menu`, `/fechar`, `p!sync` (dono).
- **explore.py** — lógica de exploração/captura (LOCATIONS, CATCH_CHANCE por bola,
  `do_capture`, `roll_encounter_level`). O explore em si roda dentro do hub.
- **spawning.py** — spawn PÚBLICO por contagem de mensagens no canal + caixas de loot.
  `/coletar` (slash) abre a caixa. Lendários/míticos AINDA aparecem aqui.
- **catching.py** — `/capturar <nome>` (captura do spawn público).
- **battle.py** — motor de UI da batalha (BattleView, botões). PvE e PvP. `/battle @user`
  (PvP com arena privada temporária). Duelo PvE é via /menu → Duelar. `award()` dá
  recompensas (escala com nível de treinador no PvE).
- **trading.py** — `/trade @user`: painel de BOTÕES (add pokémon, moedas via modal,
  confirmar, cancelar). Dupla confirmação anti-scam.
- **gyms.py** / Liga — desafios de ginásio (dentro do /menu → Liga), insígnias.
- **evolution.py** — evolução (o fluxo real está no hub; este cog é legado/prefixo).
- **pokedex.py** — comandos de coleção por prefixo (legado; hoje é tudo no /menu).
- **economy.py, items.py, progression.py, general.py, owner.py, help_tutorial.py** —
  economia, itens, missões/ranking/conquistas, utilitários, dono, ajuda.
- **admin.py** — config por servidor (cog "Administração"): setchannel, setspawn,
  setwarningchannel, setlobby, setuptitulos, togglespawns, blacklist, setprefix... 
  Requer dono OU permissão "Gerenciar Servidor".
- **gamelock.py** — apaga conversa nos canais de jogo (setchannel) e manda usar /menu.
- **welcome.py** — `on_member_join`: dá o cargo 🥚 Novato de Pallet e posta cartão de
  boas-vindas no canal do `setlobby`.

---

## 5. Sistemas principais (detalhe)

### /menu (hub) e o "só slash"
- `p!` foi **desativado para jogadores comuns** (core.py `_prefix_block_check`). Eles
  jogam por `/menu` (privado/ephemeral). Exceções públicas por prefixo:
  `PREFIX_KEEP_FOR_USERS = {"capturar", "gym"}`. Admin/dono mantêm todo o `p!`.
- Também há **trava de canal** (`_channel_lock_check`): comandos de jogo só rolam nos
  canais definidos por `setchannel` (admin e ALWAYS_ALLOWED são isentos).

### Explorar + Pesquisa de Campo + Caçada (sistema atual — SUBSTITUIU o "gacha")
- **Explore NÃO sorteia mais lendário/mítico.** Só Comum→Super-Raro.
- Cada ação dá **RP (pontos de pesquisa)**: Explorar +3, Capturar +6, Vencer PvE +10,
  Missão +20 (config).
- **Sem teto rígido** (não trava mais o ganho no dia). Em vez disso há **RETORNO
  DECRESCENTE**: até o **soft cap diário** (`research_soft_cap`, 80) rende cheio;
  o RP que passar disso é multiplicado por `research_reduced_factor` (0.4 = 40%).
  Reseta a cada dia (UTC) — ciclo diário. Lógica em `bot/utils/research.py::grant_rp`.
- RP enche uma **barra** (tela 🔬 Pesquisa no /menu, imagem Pillow) + % na Home.
- Barra cheia → **Caçada**: batalha contra o lendário (forte, IV perfeito); ao
  **VENCER**, captura. Perder não gasta RP. Custo escala por caçada; **Caçada Mítica**
  libera após N caçadas.
- Balanceado p/ ~2 semanas (casual) / ~1,5 (hardcore). Tudo em `config.py`.
- Lendário/mítico **continuam no spawn público por mensagem** (só saíram do explore).

### Batalha
- Motor em `game/battle_engine.py`: HP, PP, 5 status (queimadura/veneno/paralisia/
  sono/congelamento), **estágios de atributo** (-6..+6). Dano com STAB, tipo, crítico.
- Botões: golpes, Trocar, **🎒 Mochila**, **✨ Mega Evoluir**, Recuar/Voltar (no explore
  vira "Voltar" p/ a escolha do encontro), Desistir (PvP).
- PvP cria **arena privada temporária** (precisa Gerenciar Canais/Cargos; Admin cobre).

### Itens de batalha + Mega Evolução (implementado — ver docs/itens_batalha.md)
- **🎒 Mochila na batalha**: usa itens de `medicine` (Poções, curas de status, Éter/Elixir)
  e `battle` (X-items = +1 estágio). **Usar NÃO gasta o turno** (o jogador ainda escolhe
  golpe). Vale em PvE e PvP. Item sem efeito não é consumido. Lógica:
  `battle_engine.apply_battle_item`. Reviver (revive/max-revive) existe na loja mas
  **ainda não é usável em batalha** (preço alto).
- **✨ Mega Evolução**: pokémon que **segura a Mega Stone certa** (held item) pode Mega
  Evoluir **1x por batalha** — troca tipos/atributos/sprite; reverte no fim (nada é salvo).
  Dados de ~49 formas (Megas + Primais Kyogre/Groudon + Rayquaza) em `bot/data/mega.py`
  (indexado por `stone_key`; sprite pelo id de forma do PokéAPI). Recalcula stats via
  `battle_engine.mega_evolve` usando os IVs/natureza do próprio pokémon. **Líderes da Liga
  Suprema também Mega Evoluem** (IA, aces com pedra). Stone é **item segurável**
  (`Item.mega_stone`), não consome em batalha.
- **Segurar item**: `/menu → Coleção → detalhe → ✋ Segurar` (escolhe uma Mega Stone;
  troca devolve a anterior à mochila). Campo `Pokemon.held_item` (já existia).
- **Onde comprar**: 🛒 PokéMart, agora com **filtro por categoria** (Bolas/Curas/Batalha/
  Pedras/Boosters/Mega) — evita a enxurrada de ~49 pedras numa lista só.

### Loja / Mochila / Market
- **Loja:** comprar itens; **quantidade livre via modal** (digita quanto quer).
- **Mochila:** usar itens; boosters (Rare Candy/XP/Cristal IV) com **quantidade livre**
  (modal); pedras evoluem 1x. Não desperdiça Rare Candy no nível 100.
- **Market:** jogadores anunciam POKÉMON (preço via modal), compram entre si. Anunciar
  é paginado (vê todos os pokémon).

### Evolução
- Botão **Evoluir** mostra TODOS os caminhos disponíveis: por nível (elegíveis) + por
  pedra que o jogador JÁ tem no inventário (consome a pedra). Eevee funciona certo.
- **Sylveon (#700)** adicionado ao dataset; evolui do Eevee via item **🎀 Laço da
  Amizade** (`bond-ribbon`, comprável na Loja).

### Liga Suprema (reformulada — muito mais difícil)
- A liga ativa foi **refeita** (`bot/data/gyms.py` → `CHALLENGES`, chaves `s2_*`): 8 ginásios
  + Elite dos 4 + Campeão + 3 covis lendários + Câmara Suprema, **todos com IVs perfeitos**,
  times cheios (5-6), níveis altos (gym1 ~Nv40 → endgame Nv100) e **aces que Mega Evoluem**.
  Muito mais difícil (~3x+). Recompensas escaladas e várias **Mega Stones como prêmio**.
- **Insígnias antigas continuam válidas** para quem já as tem: a liga antiga virou
  `LEGACY_CHALLENGES` (só exibe as insígnias no perfil, não é mais desafiável). As novas têm
  nomes/emojis próprios. `CHALLENGES_BY_KEY` = ativa + legado (p/ exibição); `resolve_challenge`
  e `challenge_index` usam só a ativa. `party_slots` conta ginásios das DUAS ligas (quem já
  zerou a antiga mantém os 6 slots).
- Time do líder aceita `(espécie, nível)` ou `(espécie, nível, mega_stone_key)` — ver
  `leader_mons()`.

### Preços do PokéMart
- Preços **aumentados** (bolas, pedras, boosters, master ball, cristal de IV). Novos itens de
  batalha e Mega Stones (50k cada) somam sinks de economia.

### Títulos por nível (cargos)
- 15 cargos temáticos (bot/data/titles.py): 🥚 Novato de Pallet (nv1) → 🌌 Divindade
  Arceus (nv200). Atribuídos/criados ao abrir o /menu (bot/utils/titles.py). Admin
  cria todos com **`p!setuptitulos`**. Precisa **Gerenciar Cargos** + cargo do bot
  ACIMA dos títulos na lista.

### Boas-vindas
- `on_member_join`: dá o cargo 🥚 Novato de Pallet (ou o título certo se o jogador já
  jogou — dados são GLOBAIS por usuário) e posta cartão de imagem no canal do
  **`p!setlobby #canal`** (fundo de floresta + avatar circular).

---

## 6. Modelo de dados (bot/database/models.py)
- **User** — chave `discord_id` (ÚNICA e GLOBAL; NÃO é por servidor!). Guarda coins,
  trainer_level/xp, party, streak, total_caught/shiny, battles, quests, achievements,
  badges/badge_count, e **Pesquisa**: `research_points`, `research_day`,
  `research_today`, `hunts_won`.
  → **Implicação:** o mesmo jogador tem os MESMOS dados em qualquer servidor onde o bot
    esteja (mesmo banco). Adicionar o bot a outro servidor NÃO zera nada.
- **Pokemon** — owner_id, idx (por usuário), species_id, level, xp, IVs, nature, shiny,
  favorite, nickname, held_item.
- **Guild** — config por servidor: prefix, game_channels, redirect/warning/lobby
  channel, blacklist, spawns_enabled, language.
- **PokedexEntry** — (user, species) seen/caught.
- **MarketListing** — anúncios do market.

### AUTO-MIGRAÇÃO (importante!)
`db.py::_auto_migrate` roda no startup: compara os modelos com as tabelas e faz
`ALTER TABLE ... ADD COLUMN` para qualquer coluna nova (como **nulável**). Funciona em
Postgres e SQLite. **Então adicionar coluna nova = só declarar no modelo; sobe sozinho
no deploy.** ⚠️ Colunas novas ficam **NULL** para linhas existentes → sempre trate com
`valor or 0`/default no código (ex.: bug antigo do `badge_count` NULL).

---

## 7. Config (config.py) — constantes tunáveis
Tudo de balanceamento está em `Settings`: spawn (mensagens/cooldown/despawn), captura
(shiny_chance, coins), explore (cooldown, chances), **Pesquisa** (`research_soft_cap`,
`research_reduced_factor`, `rp_explore/capture/battle_win/quest`, `hunt_base_cost`, `hunt_cost_step`,
`mythic_hunt_cost`, `mythic_unlock_hunts`), loot, economia/daily. Ajustar aqui e
pushar.

Sprites: vêm do PokeAPI por URL. Animados (GIF) só até a gen 5 (id ≤ 649); acima cai
pra estático automaticamente (config `sprite_animated`).

---

## 8. Comandos (cheat sheet)
**Jogadores (slash):** `/menu` (tudo), `/fechar`, `/capturar <nome>`, `/coletar`,
`/battle @user`, `/trade @user`. (`p!capturar`, `p!gym` ainda funcionam por prefixo.)

**Admin (prefixo p!, precisa Gerenciar Servidor ou ser dono):**
- `p!setchannel [#canal]` — define canais de jogo (comandos+spawns).
- `p!setspawn [#canal]` / `p!redirect` — concentra spawns num canal.
- `p!setwarningchannel [#canal]` — canal que anuncia capturas raras/shiny.
- `p!setlobby [#canal]` — canal de boas-vindas.
- `p!setuptitulos` — cria os 15 cargos de título.
- `p!togglespawns`, `p!blacklist`, `p!setprefix`, `p!setlanguage`.

**Dono:** `p!sync` (re-sincroniza slash), `p!forcespawn`, `p!forceloot`.

---

## 9. Validação / testes rápidos (sem subir o bot)
```bash
# sintaxe + importa todos os cogs (pega 90% dos erros)
python -c "import importlib; [importlib.import_module('bot.cogs.'+m) for m in ['admin','spawning','catching','explore','pokedex','evolution','economy','items','trading','battle','progression','general','gyms','owner','help_tutorial','hub','gamelock','welcome']]; print('OK')"
```
(No Windows, use `PYTHONIOENCODING=utf-8` se der erro de emoji no console.)

Gotchas técnicos:
- **CRLF**: os arquivos usam CRLF; git tem `core.autocrlf=true`. Ao editar `pokemon.json`
  (grande) preserve CRLF.
- **Slash sync**: comando novo hybrid/slash só aparece após o bot reiniciar (deploy) ou
  `p!sync`.
- **Imagens**: font padrão do Pillow (DejaVu) NÃO renderiza emoji — não use emoji dentro
  das imagens geradas (só no texto do embed).

---

## 10. Decisões de design (por quê)
- **Tudo no /menu** (privado): reduz spam nos canais; `p!` aposentado p/ jogadores.
- **Lendário = conquista, não sorte**: trocamos o "gacha" do explore pela Pesquisa/Caçada
  (batalha), com teto diário pra ser justo entre casual e hardcore.
- **Dados globais por usuário**: facilita jogar em vários servidores / migrar.
- **Auto-migração**: evita gerenciar migrations manuais no Postgres de produção.

---

## 11. Planos FUTUROS (em docs/, NÃO implementado)
- **docs/itens_batalha.md** — ✅ **IMPLEMENTADO** (itens de batalha + Mega Evolução; ver
  seção 5). Falta só **reviver em batalha** (revive/max-revive existem na loja mas ainda
  não têm uso na 🎒). O doc fica como registro do desenho.
- **docs/explore_rework.md** — o plano da Pesquisa/Caçada (já IMPLEMENTADO; doc é o
  registro do desenho e decisões).
- Ideia aberta: adicionar **gerações novas (6-9)** via script do PokeAPI (sprites
  estáticos p/ os novos; movesets são automáticos por tipo).

---

## 12. Notas
- Memória do Claude Code (notas de sessão) fica em `~/.claude/projects/.../memory/` —
  é LOCAL da máquina, não vai junto no git. Este CONTEXTO.md é a fonte de verdade no repo.
- Ao concluir algo grande: commit com mensagem clara + atualizar este arquivo.
