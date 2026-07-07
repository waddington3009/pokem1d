# Plano — Rework do Explorar (sair do "Gacha")

> Planejamento. NÃO implementar até o ok. Objetivo: legendários/míticos deixarem
> de ser sorte de roleta; recompensar casuais E hardcore sem ficar fácil.

## DECISÕES JÁ TRAVADAS
- **Teto = Jeito A (retornos decrescentes):** explorar é ilimitado; o progresso de
  lendário rende cheio só nos primeiros ~25 explores/dia, depois cai. Sem Energia.
- **Barra da Caçada = IMAGEM renderizada** (Pillow, estilo cartão da Home): barra laranja
  preenchendo, %, "X / Y", silhueta do lendário. Fica numa tela nova **🔬 Pesquisa** no
  /menu + mini-indicador de % na Home.
- **Pegar o lendário = batalhar + capturar:** ao encher a barra, abre a Caçada — batalha
  difícil contra o lendário (nível/IV altos) e, ao vencer, uma captura (enfraquecer +
  arremessar). Mérito, não sorte. (Liga com o futuro sistema de itens de batalha.)
- **Sem trava de nível:** pode caçar desde cedo; o que segura é a barra ser LONGA
  (tempo/esforço), não o nível de treinador.

## PADRÕES ASSUMIDOS (dizer se quiser mudar)
- **Míticos:** mesmo sistema, mas numa barra **bem mais longa** (endgame por tempo, não por
  nível), liberada depois da 1ª lendária. Podem virar evento/semanal depois.
- **Master Ball:** não funciona na Caçada (ou é raríssima) pra não anular a batalha.
- **Lendário/Mítico saem de TODOS os pools aleatórios** (explore E spawn por mensagem) —
  só vêm pela Caçada. Spawn por mensagem continua existindo pro resto (comuns→super-raros).
- **Encontro base levemente escalado por nível:** conforme o treinador sobe, um pouco mais
  de chance de Raro no explore (sem exagero).

## Diagnóstico (com números reais do sistema atual)
- Cooldown de explore: **12s** → até **300 explores/hora**; 60% viram encontro (~180/h).
- Spawn por raridade (peso × nº de espécies): Super Raro **2%**, **Lendário 0,5%**, **Mítico 0,05%**.
- Logo, por jogador: ~**0,9 lendário/hora** esperado (e com vários jogadores, sempre tem
  alguém "sortudo"). Captura do lendário: 8% base, até 38% com Ultra, **100% com Master**.

**Por que parece fácil:** cada explore é uma roleta independente (gacha). Volume + sorte =
lendário. Um novato pode pegar um lendário no 1º clique; não há esforço/progressão; e dá pra
"spammar" 300x/hora pra forçar a raridade.

## Princípio do novo sistema: 2 camadas
1. **Loop base (determinístico, baixa variância):** explorar SEMPRE dá algo útil —
   Comum/Incomum/Raro + moedas + materiais. **Sem lendário/mítico aqui.** Sem mais "não
   achou nada" frustrante.
2. **Camada de "caça grande" (conquistada, não sorteada):** lendários/míticos vêm SÓ de um
   sistema de **progresso** (Pesquisa/Expedição), travado por nível + investimento. Não dá
   pra "ter sorte" — você constrói até lá.

## Mecânica anti-gacha: Pontos de Pesquisa (RP)
- Tirar lendário/mítico do pool aleatório (`pick_spawn_species` filtra eles).
- Cada **explore / captura / vitória / missão diária** dá **RP** (Research Points).
- RP enche uma **Trilha de Pesquisa** com marcos (deterministas):
  - **Tier 1 (barato):** Token de encontro **Raro** garantido.
  - **Tier 2:** Token **Super Raro**.
  - **Tier 3 (caro, nível 40+):** **Caça Lendária** (token).
  - **Tier 4 (muito caro, nível 80+, semanal):** **Mítico**.
- Gastar um token = **encontro/caça especial**: uma **batalha difícil** (nível alto, IV alto)
  e, ao vencer, um **desafio de captura** (enfraquecer + arremessar, estilo jogo). Skill +
  preparo, não cara-ou-coroa.

## O equilíbrio casual × hardcore (o ponto-chave)
Se fosse só acumular RP, o hardcore grindaria 300/h e dominaria. Então o **progresso de
lendário tem teto diário** — duas opções:

- **Opção A — Retornos decrescentes (recomendada):** explore continua ILIMITADO e divertido
  (commons/moedas sempre), mas o **RP** rende cheio só nos primeiros ~25 explores/dia, depois
  cai (50%, depois 10%). Hardcore farma tudo (Pokédex, IV, moedas) à vontade, mas a **caça
  lendária tem ritmo justo**. Sem muro, só desincentivo ao spam.
- **Opção B — Energia (teto duro):** explorar custa 1 Energia; cap ~50, regenera 1 a cada
  ~6 min. Casual loga e gasta o estoque; hardcore bate no teto. Mais "mobile-game", limita
  mais.

**Hardcore é recompensado** por volume em TUDO (mais capturas, moedas, IV, Pokédex, +
bônus de **streak** por dias seguidos), só não trivializa a caça lendária.
**Casual** enche a trilha de forma estável e previsível — nunca sente que perdeu na sorte.

## Tornar o lendário "merecido"
- **Caça Lendária = batalha tough** + captura em etapas (enfraquecer → arremessar). Preparo
  conta (time, itens — liga com o sistema futuro de itens de batalha).
- **Travas:** 1ª caça lendária no **nível de treinador 40+**; mítico **80+** (e talvez semanal/evento).
- **Master Ball** não entra na caça lendária (ou vira item raríssimo) pra não anular o desafio.

## Números de exemplo (tunáveis)
- RP por explore: **+2** (cheio) até 25/dia; depois **+1**; após 60 **+0,5**.
- Custo Caça Lendária: ~**500 RP**.
  - Hardcore (~25 explores cheios/dia ≈ 50 RP + missões): ~**1,5–2 semanas** p/ a 1ª.
  - Casual (~10 explores/dia ≈ 20 RP): ~**3–4 semanas**.
- Encontros base ficam **trainer-level-aware**: nível baixo vê mais Comum; conforme sobe,
  mais chance de Raro (sensação de progressão), mas lendário nunca no pool base.

## O que muda no código (visão alta — implementação depois)
- `rarity.py`: tirar lendário/mítico do `pick_spawn_species`; rebalancear; pool por nível.
- **Colunas novas em User** (auto-migradas, nuláveis — seguro p/ Postgres):
  `research_points`, `research_daily` (data+contagem p/ retornos decrescentes),
  `hunt_tokens` (JSON), `explore_streak`/`last_explore_day`.
- `hub.do_explore`: conceder RP (com decrescente), nova tabela de resultados (+materiais).
- Nova tela **"Pesquisa / Expedição"** no /menu: ver RP, trilha, gastar tokens, iniciar caça.
- Fluxo de **Caça Lendária**: reusa o motor de batalha + etapa de captura.
- (Opcional) Sistema de **Energia** se escolherem a Opção B.

## Migração / jogadores atuais
- Lendários já capturados **permanecem** (sem wipe). O novo sistema vale daqui pra frente.
- Só adiciona colunas (auto-migração). Sem reset de dados.

## Decisões a confirmar antes de implementar
1. **Teto:** Retornos decrescentes (A) ou Energia (B)?
2. **Dureza alvo:** tempo até a 1ª lendária — casual ~X semanas, hardcore ~Y? (ex.: 3 vs 1,5)
3. **Captura do lendário:** batalha + desafio (recomendado) ou token → captura garantida?
4. **Mítico:** ultra-raro semanal/evento?
5. **Encontro base por nível de treinador:** entra (commons cedo, raros depois)?
6. **Master Ball** na caça lendária: bloquear?
7. Manter o **spawn por mensagens** nos canais (caixas/encontros públicos) como está, ou
   também migrar pro mesmo modelo?
