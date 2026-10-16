# They Are Thousands — protótipo tático por turnos

Survival tático em grade 24×24 (top-down), inspirado em *They Are Billions* + *Into the Breach*.
Sobreviva 15 turnos protegendo o **Centro de Comando (CC)**; a horda final surge no fim do turno 9.

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
| `1` `2` `3` `4` `5` / botões | Construir Muro / Tenda / Balista, Reparar, Construir Tesla |
| `Esc` | Cancela modo/seleção; sem seleção abre o menu (pausa) |
| `F` / item do menu | Liga/desliga a névoa de guerra |
| `M` / item do menu | Liga/desliga a música |
| `-` `+` (menu: `←` `→`) | Volume da música |
| `N` | Próxima faixa |
| `G` | Alterna sprites / placeholders geométricos |
| Botão direito | Cancela modo/seleção |
| `Espaço` / botão | Encerrar turno |
| WASD/Setas, botão do meio, roda | Câmera e zoom |
| `Ctrl+R` (ou `R` no fim) | Reinicia (mesmo mapa personalizado, ou novo aleatório) |

## Editor de mapas
Menu → **Editor de Mapas** (`E`) ou `python main.py --editor`.
- **Ferramentas** (painel lateral): terreno (Campo, Floresta, Pedreira, Água), construções
  (CC, Tenda, Muro, Balista, Tesla, Casa Infectada), unidades (Soldado, Ranger), os 5 tipos de
  zumbi e Borracha. Clique e **arraste** para pintar (ótimo para linhas de muro); botão direito apaga.
- **Qtd** (`[` `]`): zumbis por enxame (limitado pela pilha máx. do tipo) e recurso do depósito.
  **Pincel** (`B`): 1x1 ou 3x3 para terreno/borracha.
- Sempre há exatamente 1 CC: colocar outro o move; ele não pode ser apagado nem ficar fora do Campo.
  Construções transformam o tile em Campo; Água remove o que houver no tile.
- `Ctrl+Z`/`Ctrl+Y` desfazer/refazer, **Vazio**/**Aleatório** criam um novo mapa base.
- Clique no nome para renomear; **Salvar** (`Ctrl+S`) grava `maps/<nome>.json`; a lista de
  mapas salvos no painel carrega com um clique.
- **Jogar** (`F5`) inicia uma partida com o mapa atual. No menu, **Mapa: ...** alterna entre
  Aleatório e os mapas salvos para a **Nova Partida**. Ondas e horda final continuam vindo das bordas.
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
aparecem a partir das ondas dos turnos 6 e 8 e na horda final. Casas Infectadas geram Errantes.

## Névoa de guerra (FOW)
Adaptada de *They Are Billions*; liga/desliga pelo menu inicial/pausa ou `F`, a qualquer momento.
- **Inexplorado** (preto): nada é conhecido. **Explorado** (escurecido): terreno e construções
  ficam na memória, mas zumbis não aparecem. **Visível**: raio circular de visão aliado
  (CC 6, Ranger 6, Balista 5, Soldado 4, Tesla 4, Tenda 3, Muro 2).
- Só é possível atacar (unidades e Balistas) enxames visíveis; o HUD mostra apenas zumbis à vista.
- Movimentos podem atravessar a névoa: se um enxame oculto ou terreno desconhecido bloquear o
  caminho, a unidade para antes (**emboscada**) e perde o movimento.

## Território
Só se constrói dentro do território (contorno azul no mapa): raio 4 do CC e raio 3 de cada
**Torre Tesla** (`5`, 1 AP, 3 Ouro, 2 Madeira, HP 4). Tendas, Balistas e Muros não expandem.
Construa Teslas na borda para avançar; se uma Tesla cair, o território dela some.

## Fases do turno
1. **Jogador** – gasta AP global (construir, reparar, atacar, coletar). Cada unidade move 1× e age 1×.
2. **Som** – ações emitem ruído (raio Manhattan); enxames no raio são atraídos à fonte.
3. **Zumbis** – enxames tipados (pilhas por tile) seguem campo de fluxo Dijkstra até alvos civis/som; pilhas do mesmo tipo se fundem.
4. **Defesas** – Balistas disparam automaticamente.
5. **Ataque/Infecção** – enxames atacam vizinhos (Cuspidores à distância); Tenda com HP 0 vira Casa Infectada que gera zumbis.
6. **Fim de rodada** – produção de ouro, ondas nas bordas, checagem de vitória.

## Balanceamento (CSV)
Os stats ficam em `data/` (um arquivo por categoria, uma linha por tipo, `id` como chave).
Edite no Excel/LibreOffice ou num editor de texto e **reinicie o jogo** para aplicar.

| Arquivo | Colunas principais |
|---|---|
| `data/buildings.csv` | `buildable` (aparece nos botões), custo `ap/gold/wood/stone`, `hp`, `noise` (ao construir), `gold_income`, `vision`, `build_radius` (território), `attack_range`/`damage`/`attack_noise` (defesa automática), `spawn` (Casa Infectada) |
| `data/units.csv` | `hp`, `move`, `attack_range`, `damage`, `noise` (ao atacar), `vision` |
| `data/zombies.csv` | `hp` (por zumbi), `speed`, `attack` (dano por zumbi), `max_stack` (≤ 10), `attack_range`, `structure_mult`, `flying`, `hearing`, `color` (`#rrggbb`), `description` |

- Separador `,` ou `;` (detectado automaticamente); com `;` aceita vírgula decimal (Excel pt-BR).
- Booleanos: `0/1`, `true/false`, `sim/nao`. Coluna `notes` é livre. Linhas com `id` iniciado por `#` são ignoradas.
- Erros (coluna ausente, valor inválido, id faltando/duplicado) abortam com arquivo, linha e coluna.
- Construções/unidades têm ids fixos (`hq, tent, wall, ballista, tesla, infected` / `soldier, ranger`).
  Novos **tipos de zumbi** podem ser criados só no CSV (usam o visual geométrico com a `color`);
  para aparecerem nas ondas, adicione-os em `WAVES`/`FINAL_HORDE` no `config.py`.
- Qualquer construção com `attack_range` e `damage` > 0 dispara na fase de defesa.
- Regras gerais (AP por turno, ondas, recursos iniciais, reparo/coleta) continuam em `game/config.py`.

## Estrutura
- `data/*.csv` – stats de construções, unidades e zumbis (balanceamento)
- `game/stats.py` – leitura/validação dos CSVs
- `game/config.py` – regras gerais, ondas, layout, cores
- `game/grid.py` – `Grid`, `Tile`, `Terrain`, distâncias, BFS/Dijkstra
- `game/entities.py` – `Building` (CC, Tenda, Muro, Balista, Tesla, Casa Infectada), `Unit` (Soldado, Ranger), `ZombieSwarm` (tipado)
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
