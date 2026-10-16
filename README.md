# They Are Thousands — protótipo tático por turnos

Survival tático em grade 24×24 (top-down), inspirado em *They Are Billions* + *Into the Breach*.
Sobreviva 15 turnos protegendo o **Centro de Comando (CC)**; a horda final surge no fim do turno 9.

```bash
pip install -r requirements.txt
python main.py            # mapa aleatório
python main.py --seed 42  # mapa determinístico
python -m unittest discover -s tests -t .
```

## Controles
| Entrada | Ação |
|---|---|
| Clique em unidade | Seleciona (azul = mover, vermelho = atacar, amarelo = coletar) |
| `1` `2` `3` `4` / botões | Construir Muro / Tenda / Balista, Reparar |
| Botão direito / `Esc` | Cancela modo/seleção |
| `Espaço` / botão | Encerrar turno |
| WASD/Setas, botão do meio, roda | Câmera e zoom |
| `Ctrl+R` (ou `R` no fim) | Novo mapa |

## Fases do turno
1. **Jogador** – gasta AP global (construir, reparar, atacar, coletar). Cada unidade move 1× e age 1×.
2. **Som** – ações emitem ruído (raio Manhattan); enxames no raio são atraídos à fonte.
3. **Zumbis** – enxames (1–10 por tile) seguem campo de fluxo Dijkstra até alvos civis/som, fundem-se ao se encontrarem.
4. **Defesas** – Balistas disparam automaticamente.
5. **Ataque/Infecção** – enxames atacam vizinhos; Tenda com HP 0 vira Casa Infectada que gera zumbis.
6. **Fim de rodada** – produção de ouro, ondas nas bordas, checagem de vitória.

## Estrutura
- `game/config.py` – balanceamento, custos, cores
- `game/grid.py` – `Grid`, `Tile`, `Terrain`, distâncias, BFS/Dijkstra
- `game/entities.py` – `Building` (CC, Tenda, Muro, Balista, Casa Infectada), `Unit` (Soldado, Ranger), `ZombieSwarm`
- `game/world.py` – regras e simulação (sem pygame)
- `game/turns.py` – máquina de estados das fases
- `game/renderer.py` – câmera (offset/zoom) e desenho
- `game/hud.py` – painel lateral
- `game/app.py` – loop principal e entrada
