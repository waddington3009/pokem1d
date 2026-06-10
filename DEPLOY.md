# 🚀 Deploy do PokeM1D na VPS com EasyPanel + PostgreSQL

Guia passo a passo para hospedar o bot 24/7 usando **EasyPanel** (Docker) e um
banco **PostgreSQL** gerenciado pelo próprio EasyPanel.

> Por que Docker + Postgres? O container fica **stateless** (sem dados dentro dele):
> todo o estado vive no Postgres. Assim você pode reiniciar/atualizar o bot sem
> perder nada, e o EasyPanel cuida de manter tudo no ar.

---

## ✅ Pré-requisitos
- VPS com EasyPanel instalado e funcionando.
- Token do bot (Discord Developer Portal) com **MESSAGE CONTENT** e **SERVER MEMBERS** intents ativados.
- O código em um repositório **GitHub** (privado serve). *(Alternativas sem GitHub no fim.)*

---

## 1) Suba o código para o GitHub

No seu PC, dentro da pasta do projeto:

```bash
git init
git add .
git commit -m "PokeM1D - bot de Pokémon"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/PokeM1D.git
git push -u origin main
```

> O `.gitignore` já protege o `.env` e os `*.db` — seus segredos **não** vão para o repositório.
> O `Dockerfile` e o `.dockerignore` já estão prontos na raiz.

---

## 2) Crie o projeto e o banco no EasyPanel

1. No EasyPanel: **Create Project** → nome `pokem1d`.
2. Dentro do projeto: **+ Service → Postgres**.
   - Service name: `db`
   - Versão: 16 (ou a sugerida)
   - Clique **Create**.
3. Abra o serviço `db` → aba **Credentials**. Anote:
   - **Host (internal)** — algo como `pokem1d_db`
   - **Port** — `5432`
   - **User**, **Password**, **Database**

> Serviços do mesmo projeto se enxergam pela rede interna do Docker usando o
> *Host (internal)*. Não precisa expor o Postgres para a internet.

---

## 3) Monte a `DATABASE_URL`

O SQLAlchemy async precisa do driver **asyncpg**. Monte assim:

```
postgresql+asyncpg://USER:PASSWORD@HOST:5432/DATABASE
```

Exemplo com os dados do EasyPanel:

```
postgresql+asyncpg://postgres:Ab12Cd34@pokem1d_db:5432/pokem1d
```

⚠️ **Atenção:**
- Se o EasyPanel mostrar uma URL começando com `postgres://...`, troque o início por
  `postgresql+asyncpg://` e **remova** qualquer `?sslmode=disable` do final.
- Se a senha tiver caracteres especiais (`@ : / #`), regenere uma senha só com
  letras/números **ou** faça URL-encode deles.

---

## 4) Crie o serviço do bot (App via Dockerfile)

1. No projeto `pokem1d`: **+ Service → App**.
   - Service name: `bot`
2. Aba **Source**:
   - Selecione **GitHub** → conecte sua conta → escolha o repo `PokeM1D` e a branch `main`.
3. Aba **Build**:
   - Build method: **Dockerfile**
   - Dockerfile path: `Dockerfile` (padrão)
4. Aba **Environment** — cole as variáveis (uma por linha):
   ```env
   DISCORD_TOKEN=seu_token_aqui
   DATABASE_URL=postgresql+asyncpg://postgres:Ab12Cd34@pokem1d_db:5432/pokem1d
   DEFAULT_PREFIX=p!
   OWNER_IDS=SEU_ID_DO_DISCORD
   DEFAULT_LANGUAGE=pt
   ```
5. **Domains / Ports:** *não configure nada* — um bot do Discord só faz conexões
   de saída, não recebe HTTP. Pode ignorar/remover qualquer domínio.
6. Clique **Deploy**.

O bot cria as tabelas no Postgres sozinho no primeiro start (`init_db` → `create_all`).
Nenhuma migração manual é necessária.

---

## 5) Verifique

Abra o serviço `bot` → aba **Logs**. Você deve ver algo como:

```
Pokédex carregada: 63 espécies
Banco de dados inicializado.
Extensão carregada: bot.cogs.explore
...
Conectado como SeuBot#1234 (ID ...)
```

No Discord, rode `p!start` e `p!explore`. 🎉

---

## 🔄 Atualizações futuras

Sempre que mudar o código:

```bash
git add . && git commit -m "ajustes" && git push
```

No EasyPanel, abra o serviço `bot` → **Deploy** (ou ative *Auto Deploy* na aba
Source para fazer deploy automático a cada push). O EasyPanel reconstrói a imagem
e reinicia — sem perder dados, pois estão no Postgres.

---

## 🧰 Alternativas para enviar o código (sem GitHub)

- **Git genérico:** EasyPanel também aceita uma URL `.git` qualquer (GitLab, Gitea, etc.)
  na aba Source.
- **Imagem no registry:** construa e publique a imagem, depois use Source → *Image*:
  ```bash
  docker build -t SEU_USUARIO/pokem1d:latest .
  docker push SEU_USUARIO/pokem1d:latest
  ```

---

## 🐛 Problemas comuns

| Sintoma nos logs | Causa / solução |
|---|---|
| `DISCORD_TOKEN não definido` | Variável não chegou — confira a aba Environment do serviço `bot`. |
| `PrivilegedIntentsRequired` | Ative **Message Content** e **Server Members** no Developer Portal. |
| `Connection refused` / `does not exist` no Postgres | `HOST`/`DATABASE` errados na `DATABASE_URL`, ou o serviço `db` ainda subindo. |
| `InvalidPasswordError` | Senha errada ou com caractere especial não-encodado. |
| `Can't load plugin: sqlalchemy.dialects:postgresql.asyncpg` | Faltou `asyncpg` (já está no `requirements.txt`) — refaça o build. |
| Bot reinicia em loop | Veja o traceback nos Logs; quase sempre é `DATABASE_URL` ou token. |

---

## 💾 Backup do banco (recomendado)

No serviço `db` do EasyPanel há a opção de **Backups** (agende para S3 ou local).
Ative para não perder o progresso dos jogadores.
