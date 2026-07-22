# Mapeamento — Itens de Batalha + Mega Evolução

> Planejamento (NÃO implementado ainda). Mecânica real de batalha estilo jogos:
> botão 🎒 Mochila para usar itens durante a luta + ✨ Mega Evoluir.

## O que o motor JÁ suporta (não precisa criar)
- **HP / desmaio**: `BattleMon.hp`, `max_hp`, `alive`.
- **Status** (5): `burn | poison | paralyze | sleep | freeze` + `sleep_turns`.
- **PP por golpe**: `BattleMon.pp` (dict por golpe).
- **Estágios de atributo** (-6..+6) p/ `atk/def/spa/spd/spe`: `BattleMon.stages` + `stage_multiplier`.
  (NÃO há estágio de *precisão/evasão* — então X-Precisão/X-Evasão ficam de fora.)
- **Item segurado**: a tabela `Pokemon` já tem a coluna `held_item` (hoje sem uso em batalha).

## Infra NOVA a criar (resumo p/ a fase de implementação)
1. Campo `held_item` no `BattleMon` (lido de `pokemon.held_item` no `build_battle_mon`).
2. Botão **🎒 Mochila** na batalha → lista itens usáveis → usar **gasta o turno** (como nos jogos).
3. Botão **✨ Mega Evoluir** → aparece se o ativo segura a Mega Stone certa; 1x por batalha.
4. Formas Mega como **espécies** (dados + IDs de sprite especiais) + **reverter** ao fim da luta.
5. UI no `/menu` (detalhe do pokémon) p/ **segurar/remover** um item (held item).
6. Nova categoria de item `medicine` (e `mega-stone`) em `bot/data/items.py`.

---

## 1) Itens de cura de HP  (categoria `medicine`)
| key | nome | efeito | preço sugerido |
|---|---|---|---|
| `potion` | Poção | +20 HP | 2000 |
| `super-potion` | Super Poção | +60 HP | 5000 |
| `hyper-potion` | Hyper Poção | +120 HP | 15.500 |
| `max-potion` | Poção Máxima | HP total | 20.800 |
| `full-restore` | Restaurador Total | HP total **+ cura status** | 40.000 |

## 2) Cura de status  (categoria `medicine`)
| key | nome | efeito |
|---|---|---|
| `antidote` | Antídoto | cura veneno |
| `burn-heal` | Antiqueimadura | cura queimadura |
| `paralyze-heal` | Antiparalisia | cura paralisia |
| `awakening` | Despertar | cura sono |
| `ice-heal` | Antigelo | cura congelamento |
| `full-heal` | Cura Total | cura **qualquer** status |

## 3) Reviver  (categoria `medicine`)
| key | nome | efeito |
|---|---|---|
| `revive` | Reviver | revive um pokémon desmaiado com **50% HP** |
| `max-revive` | Reviver Máximo | revive com **100% HP** |

## 4) Restaurar PP  (categoria `medicine`)
| key | nome | efeito |
|---|---|---|
| `ether` | Éter | +10 PP de **um** golpe |
| `max-ether` | Éter Máximo | PP total de **um** golpe |
| `elixir` | Elixir | +10 PP de **todos** os golpes |
| `max-elixir` | Elixir Máximo | PP total de todos |

## 5) Boost de atributo em batalha — "X-items"  (categoria `battle`)
Usam os **estágios que já existem** (+1 estágio por uso, dura a batalha).
| key | nome | efeito |
|---|---|---|
| `x-attack` | X Ataque | +1 estágio de Atk |
| `x-defense` | X Defesa | +1 estágio de Def |
| `x-sp-atk` | X Atq. Esp. | +1 estágio de SpA |
| `x-sp-def` | X Def. Esp. | +1 estágio de SpD |
| `x-speed` | X Velocidade | +1 estágio de Spe |

## 6) Mega Stones  (categoria `mega-stone`, item **segurado**, não consome)
Cada pedra liga uma espécie à sua forma Mega. Mecânica: segurar a pedra → botão
**✨ Mega Evoluir** (1x/batalha) → troca stats/tipos/sprite → reverte ao fim.
Algumas espécies têm **duas** megas (X/Y).

Set inicial sugerido (ícones; o resto segue o mesmo padrão conforme adicionamos as espécies):
| pedra | espécie → Mega |
|---|---|
| `venusaurite` | Venusaur → Mega Venusaur |
| `charizardite-x` | Charizard → Mega Charizard X |
| `charizardite-y` | Charizard → Mega Charizard Y |
| `blastoisinite` | Blastoise → Mega Blastoise |
| `mewtwonite-x` | Mewtwo → Mega Mewtwo X |
| `mewtwonite-y` | Mewtwo → Mega Mewtwo Y |
| `gengarite` | Gengar → Mega Gengar |
| `lucarionite` | Lucario → Mega Lucario |
| `gyaradosite` | Gyarados → Mega Gyarados |
| `tyranitarite` | Tyranitar → Mega Tyranitar |
| `garchompite` | Garchomp → Mega Garchomp |
| `metagrossite` | Metagross → Mega Metagross |
| `absolite` | Absol → Mega Absol |
| `salamencite` | Salamence → Mega Salamence |
| `aggronite` | Aggron → Mega Aggron |
| `scizorite` | Scizor → Mega Scizor |

> Total real de Megas ~48. Lançar com um set inicial e ir somando.

---

## Decisões a confirmar antes de implementar
1. **Itens valem em PvP** também, ou só PvE (selvagem/ginásio/duelo)?
Valem em PvP
2. **Usar item gasta o turno?** (recomendado: sim, como nos jogos)
Não gasta o turno
3. **Quantas Megas no lançamento** (set inicial vs. todas as ~48)?
Todos os Megas
4. **X-items entram?** (precisão/evasão ficam de fora por falta de estágio no motor)
Sim
5. **Onde comprar / preços** (PokéMart já existente).
No PokeMart
6. **Como segurar item**: tela no `/menu` (detalhe) com "Segurar item / Remover".
Confirmado
7. **Reviver em batalha** mexe em pokémon desmaiado do time — confirmar se entra já.
Não entra já e pode se eu determinei algum preço para esse item pode ignorar e colocar um preço bem mais caro.
