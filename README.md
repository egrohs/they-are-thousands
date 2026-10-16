# They Are Thousands — protótipo tático por turnos

Survival tático em grade 24×24 (top-down), inspirado em *They Are Billions* + *Into the Breach*.
Sobreviva 15 turnos protegendo o **Centro de Comando (CC)**; ondas programadas chegam a cada 3 turnos por uma borda anunciada e a horda final vem no turno 12.

```bash
pip install -r requirements.txt
python main.py            # mapa aleatório
python main.py --seed 42  # mapa determinístico
python main.py --no-fog  # começa com névoa de guerra desligada
python main.py --no-music  # começa sem trilha sonora
python main.py --editor    # abre direto no editor de mapas
python main.py --map maps/meu_mapa.json  # joga um mapa personalizado
python -m unittest discover -s tests -t .
```

## Controles
| Entrada | Ação |
|---|---|
| Clique em unidade | Seleciona (azul = mover, vermelho = atacar, amarelo = coletar) |
| `1` … `8` / botões | Construir Muro / Tenda / Balista, Reparar, Construir Tesla / Torre de Vigia / Serraria / Extrator de Pedra |
| `Esc` | Cancela modo/seleção; sem seleção abre o menu (pausa) |
| `F` / item do menu | Liga/desliga a névoa de guerra |
| `M` / item do menu | Liga/desliga a música |
| `-` `+` (menu: `←` `→`) | Volume da música |
| `N` | Próxima faixa |
| `G` | Alterna sprites / placeholders geométricos |
| Botão direito | Cancela modo/seleção |
| `Espaço` / botão | Encerrar turno |
| `Z` / `Backspace` / botão | Desfazer última ação (veja abaixo) |
| WASD/Setas, botão do meio, roda | Câmera e zoom |
| `Ctrl+R` (ou `R` no fim) | Reinicia (mesmo mapa personalizado, ou novo aleatório) |

## Desfazer

Construir, reparar, mover, atacar e coletar podem ser desfeitos (`Z`, `Backspace` ou botão
**Desfazer (N)**), em sequência, até 30 ações (`UNDO_LIMIT` em `config.py`):

- vale só para o turno atual: ao encerrar o turno o histórico é apagado;
- estilo Into the Breach: se uma ação **revela informação** (explora névoa, avista zumbis novos ou
  sofre emboscada), ela e todas as anteriores ficam travadas;
- com a FOW desligada nada é revelado, então o desfazer está sempre disponível;
- abrir caixas não trava o histórico (o conteúdo já aparece na inspeção).

## Editor de mapas
Menu → **Editor de Mapas** (`E`) ou `python main.py --editor`.
- **Ferramentas** (painel lateral): terreno (Campo, Floresta, Pedreira, Água), construções
  (CC, Tenda, Muro, Balista, Tesla, Torre de Vigia, Serraria, Extrator, Casa Infectada), unidades (Soldado, Ranger), os 5 tipos de
  zumbi, as **caixas de recursos** e Borracha. Clique e **arraste** para pintar (ótimo para linhas de muro); botão direito apaga.
- **Qtd** (`[` `]`): zumbis por enxame (limitado pela pilha máx. do tipo) e recurso do depósito.
  **Pincel** (`B`): 1x1 ou 3x3 para terreno/borracha.
- Sempre há exatamente 1 CC: colocar outro o move; ele não pode ser apagado nem ficar fora do Campo.
  Construções transformam o tile em Campo; Floresta, Pedreira e Água removem o que houver no tile
  (unidades e zumbis só ficam em Campo).
- `Ctrl+Z`/`Ctrl+Y` desfazer/refazer, **Vazio**/**Aleatório** criam um novo mapa base.
- Clique no nome para renomear; **Salvar** (`Ctrl+S`) grava `maps/<nome>.json`; a lista de
  mapas salvos no painel carrega com um clique.
- **Jogar** (`F5`) inicia uma partida com o mapa atual. No menu, **Mapa: ...** alterna entre
  Aleatório e os mapas salvos para a **Nova Partida**. Ondas e horda final seguem o cronograma de `data/waves.csv`.
- Formato JSON documentado em `game/maps.py` (validado ao carregar, com mensagens de erro).

## Trilha sonora
Todos os arquivos `.mp3/.ogg/.wav/.flac` em `assets/audio/music/` tocam em ordem alfabética,
em loop, com fade. Sem dispositivo de áudio ou com arquivo inválido, o jogo segue sem música.

## Sprites
Imagens de `assets/images/` (mapeadas em `SPRITE_FILES` no `config.py`) são recortadas para o tile
e reescaladas conforme o zoom:
- `ranger.png` → Ranger; `tend.png` → Tenda (e Casa Infectada, tingida de verde).
- Zumbis por tipo: Errante `zombie.png`, Corredor `runner.png`, Brutamontes `executor.png`;
  Harpia (`runner.png` roxo) e Cuspidor (`zombie.png` verde). Letra do tipo no canto superior,
  quantidade no selo inferior (vermelho = agressivo; borda laranja = atraído por barulho).
- Sem imagem (Soldado, CC, Muro, Balista, Tesla) ou arquivo ausente → placeholder geométrico.

## Tipos de zumbi
Inspirados em *They Are Billions* (atributos em `data/zombies.csv`). Cada tile guarda
uma pilha de um único tipo; pilhas de tipos diferentes não se fundem.

| Tipo | Letra | HP cada | Vel. | Pilha máx. | Habilidade |
|---|---|---|---|---|---|
| Errante | Z | 1 | 2 | 10 | Comum; forte em grandes pilhas |
| Corredor | C | 1 | 3 | 8 | Rápido; ouve barulho +2 tiles mais longe |
| Brutamontes | B | 3 | 1 | 4 | Resistente; dano ×2 em construções |
| Harpia | H | 1 | 3 | 5 | Salta por cima de Muros/Balistas/Teslas |
| Cuspidor | V | 2 | 2 | 5 | Ataque à distância (2 tiles); para ao ter alvo no alcance |

Dano do enxame = `ceil(quantidade × dano do tipo)`. Tipos com HP > 1 acumulam ferimentos
entre ataques. Os primeiros turnos trazem Errantes/Corredores; Brutamontes, Harpias e Cuspidores
aparecem a partir da onda do turno 9 e na horda final. Casas Infectadas geram Errantes.

## Ondas programadas
Como em *They Are Billions*, as ondas seguem um cronograma fixo (`data/waves.csv`): ondas pequenas
nos turnos **3, 6 e 9**, cada uma entrando por **uma única borda**, e a **horda final** no turno
**12**, vindo de duas bordas ao mesmo tempo. A borda e o ponto de entrada são sorteados no início da
partida (determinísticos pela seed), então dá para se preparar:
- **Indicador no mapa** (a partir de 3 turnos antes): faixa vermelha na borda de entrada, seta
  apontando para dentro e contagem (`ONDA em 2`, `ONDA!` no turno de chegada, piscando). Se a
  entrada estiver fora da tela, uma seta presa à borda da tela aponta para ela.
- **HUD**: `Onda: Norte ~8 - em 2 turno(s)`; o log de eventos anuncia cada próxima onda.
- A onda chega no fim do turno indicado, perto do ponto anunciado (±4 tiles ao longo da borda).

## Névoa de guerra (FOW)
Adaptada de *They Are Billions*; liga/desliga pelo menu inicial/pausa ou `F`, a qualquer momento.
- Quatro camadas:
  - **Inexplorado** (preto): nada é conhecido.
  - **Escuridão** (preto azulado): já explorado, mas **sem unidade/construção aliada por perto**
    (além de visão + 3 tiles, `FOG_MEMORY_MARGIN` em `config.py`). Oculta **tudo**: terreno,
    recursos, construções (inclusive Casas Infectadas), caixas e zumbis. Reaparece quando um
    aliado volta para perto.
  - **Memória** (escurecido): explorado e perto de aliados; terreno, construções e caixas
    aparecem, mas zumbis não.
  - **Visível**: raio circular de visão aliado
    (CC 6, Ranger 6, Balista 5, Soldado 4, Tesla 4, Tenda 3, Muro 2).
- Só é possível atacar (unidades e Balistas) enxames visíveis; o HUD mostra apenas zumbis à vista.
- Movimentos podem atravessar a névoa: se um enxame oculto ou terreno desconhecido (inexplorado/escuridão) bloquear o
  caminho, a unidade para antes (**emboscada**) e perde o movimento.

## Território
Só se constrói dentro do território (contorno azul no mapa): raio 4 do CC e raio 3 de cada
**Torre Tesla** (`5`, 1 AP, 3 Ouro, 2 Madeira, HP 4). Tendas, Balistas e Muros não expandem.
Construa Teslas na borda para avançar; se uma Tesla cair, o território dela some.

## Serraria e Extrator de Pedra
Produção passiva, como no *They Are Billions*: a construção explora o terreno ao redor
(raio 2, área 5x5) e rende no **fim de cada turno**, sem esgotar os depósitos.

| Construção | Tecla | Custo | Produção |
|---|---|---|---|
| **Serraria** | `7` | 2 AP, 4 Ouro, 2 Madeira, HP 6 | +1 Madeira a cada 2 tiles de Floresta no raio (máx. 4/turno) |
| **Extrator de Pedra** | `8` | 2 AP, 4 Ouro, 4 Madeira, HP 6 | +1 Pedra a cada 2 tiles de Pedreira no raio (máx. 3/turno) |

- Áreas sobrepostas **não somam**: cada tile serve a um único extrator do mesmo recurso (o
  mais antigo). Ao posicionar, o mapa contorna os tiles livres e mostra `+N/turno`; o
  Inspetor detalha a produção. Selecionar um extrator construído destaca os tiles dele.
- O HUD mostra a renda por turno ao lado de cada recurso, ex.: `Madeira: 12 (+3)`.
- Coletar com unidades continua possível (e esgota o tile, abrindo passagem); um tile
  esgotado vira Campo e deixa de render para o extrator.

## Caixas de recursos
Mapas aleatórios espalham **7 caixas** fora da base (cada tipo tem distância mínima do centro;
o sorteio usa RNG próprio, então não altera terreno nem zumbis). Ficam escondidas pela névoa
até a área ser explorada. Uma unidade que **passa por cima ou para** na caixa a abre na hora,
sem gastar AP/ação; construir sobre ela também a coleta. O HUD mostra `Caixas: x/7` e o
Inspetor revela o conteúdo.

| Caixa | Conteúdo | Observação |
|---|---|---|
| Suprimentos | +3 Ouro, +3 Madeira, +1 Pedra | comum |
| Baú de Ouro | +8 Ouro | |
| Madeira Estocada | +8 Madeira | |
| Pedras Lavradas | +6 Pedra | |
| Esconderijo Militar | +8 Ouro, +6 Madeira, +4 Pedra | raro, longe; **alarme** (ruído 3) atrai zumbis |

## Torre de Vigia
**Torre de Vigia** (`6`, 2 AP, 2 Ouro, 4 Madeira, 1 Pedra, HP 10) — como no They Are Billions:
- Sozinha ela **não ataca**; mova um Soldado ou Ranger para o tile da torre (é destino, nunca
  passagem). A unidade fica abrigada: **+2 alcance** e **+3 visão**.
- Zumbis atacam a **torre**, não a unidade (Harpias não saltam torres ocupadas). Se a torre cair,
  a unidade fica exposta nos escombros.
- Na fase de Defesas, a unidade abrigada que **não agiu** no turno dispara de graça (sem AP) no
  enxame visível mais próximo, com o ruído normal da arma. Atacar manualmente também usa o alcance
  bônus. Para sair, basta mover a unidade para outro tile.

## Terreno
Só o **Campo** é atravessável. **Floresta**, **Pedreira** e **Água** bloqueiam o movimento de todas
as unidades e de todos os zumbis (inclusive Harpias, que só saltam construções). Florestas e
pedreiras funcionam como barreiras naturais e podem ser coletadas de um tile vizinho (inclusive na
diagonal); ao esgotar, viram Campo e abrem passagem. Mapas aleatórios nunca geram bolsões de Campo
isolados (eles viram Floresta), e as ondas entram por tiles da borda com caminho até a base.

## Fases do turno
1. **Jogador** – gasta AP global (construir, reparar, atacar, coletar). Cada unidade move 1× e age 1×.
2. **Som** – ações emitem ruído (raio Manhattan); enxames no raio são atraídos à fonte.
3. **Zumbis** – enxames tipados (pilhas por tile) seguem campo de fluxo Dijkstra até alvos civis/som; pilhas do mesmo tipo se fundem.
4. **Defesas** – Balistas disparam automaticamente; unidades ociosas em Torres de Vigia também.
5. **Ataque/Infecção** – enxames atacam vizinhos (Cuspidores à distância); Tenda com HP 0 vira Casa Infectada que gera zumbis.
6. **Fim de rodada** – produção (Ouro de Tendas/CC, Madeira de Serrarias, Pedra de Extratores), ondas programadas na borda anunciada, checagem de vitória.

## Balanceamento (CSV)
Os stats ficam em `data/` (um arquivo por categoria, uma linha por tipo, `id` como chave).
Edite no Excel/LibreOffice ou num editor de texto e **reinicie o jogo** para aplicar.

| Arquivo | Colunas principais |
|---|---|
| `data/buildings.csv` | `buildable` (aparece nos botões), custo `ap/gold/wood/stone`, `hp`, `noise` (ao construir), `gold_income`, `vision`, `build_radius` (território), `attack_range`/`damage`/`attack_noise` (defesa automática), `spawn` (Casa Infectada), `garrison`/`range_bonus`/`vision_bonus` (abrigo de unidade e bônus concedidos — Torre de Vigia), `harvest` (`wood`/`stone`)/`harvest_radius`/`harvest_tiles` (tiles por 1 recurso)/`harvest_max` (extratores) |
| `data/units.csv` | `hp`, `move`, `attack_range`, `damage`, `noise` (ao atacar), `vision` |
| `data/zombies.csv` | `hp` (por zumbi), `speed`, `attack` (dano por zumbi), `max_stack` (≤ 10), `attack_range`, `structure_mult`, `flying`, `hearing`, `color` (`#rrggbb`), `description` |
| `data/crates.csv` | caixas de recursos: `weight` (raridade; 0 = só no editor), `gold`/`wood`/`stone` (conteúdo), `noise` (alarme ao abrir), `min_dist` (distância mínima do centro), `color` (#rrggbb). Quantidade e espaçamento: `CRATE_COUNT`/`CRATE_SPACING` em `config.py` |
| `data/waves.csv` | `turn` (chega ao fim dele), `direction` (`N`, `S`, `L`, `O` ou `?` = sorteada; `?1`/`?2` = bordas sorteadas distintas no mesmo turno), `kind`, `swarms`, `size`, `final` (1 = horda final, um único turno) |

- Separador `,` ou `;` (detectado automaticamente); com `;` aceita vírgula decimal (Excel pt-BR).
- Booleanos: `0/1`, `true/false`, `sim/nao`. Coluna `notes` é livre. Linhas com `id` iniciado por `#` são ignoradas.
- Erros (coluna ausente, valor inválido, id faltando/duplicado) abortam com arquivo, linha e coluna.
- Construções/unidades têm ids fixos (`hq, tent, wall, ballista, tesla, infected` / `soldier, ranger`).
  Novos **tipos de zumbi** podem ser criados só no CSV (usam o visual geométrico com a `color`);
  para aparecerem nas ondas, adicione linhas em `data/waves.csv`.
- Qualquer construção com `attack_range` e `damage` > 0 dispara na fase de defesa.
- Regras gerais (AP por turno, recursos iniciais, reparo/coleta, aviso de ondas) continuam em `game/config.py`.

## Estrutura
- `data/*.csv` – stats de construções, unidades e zumbis + cronograma de ondas (balanceamento)
- `game/stats.py` – leitura/validação dos CSVs
- `game/config.py` – regras gerais, layout, cores
- `game/grid.py` – `Grid`, `Tile`, `Terrain`, distâncias, BFS/Dijkstra
- `game/entities.py` – `Building` (CC, Tenda, Muro, Balista, Tesla, Torre de Vigia, Serraria, Extrator de Pedra, Casa Infectada), `Unit` (Soldado, Ranger), `ZombieSwarm` (tipado)
- `game/world.py` – regras e simulação (sem pygame)
- `game/turns.py` – máquina de estados das fases
- `game/renderer.py` – câmera (offset/zoom) e desenho
- `game/hud.py` – painel lateral
- `game/fog.py` – névoa de guerra (visível/explorado)
- `game/audio.py` – player da trilha sonora
- `game/sprites.py` – carregamento/cache das imagens de unidades e construções
- `game/maps.py` – formato JSON de mapas, validação, salvar/carregar (`maps/`)
- `game/editor.py` – editor de mapas (`MapEditor` lógica + `EditorScreen` interface)
- `game/menu.py` – menu inicial/pausa e configurações
- `game/app.py` – loop principal e entrada
