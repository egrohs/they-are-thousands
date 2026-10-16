# They Are Thousands — protótipo tático por turnos

Survival tático em grade 24×24 (top-down), inspirado em *They Are Billions* + *Into the Breach*.
Sobreviva 15 turnos protegendo o **Centro de Comando (CC)**; a horda final surge no fim do turno 9.

```bash
pip install -r requirements.txt
python main.py            # mapa aleatório
python main.py --seed 42  # mapa determinístico
python main.py --no-fog  # começa com névoa de guerra desligada
python main.py --no-music  # começa sem trilha sonora
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
| Botão direito | Cancela modo/seleção |
| `Espaço` / botão | Encerrar turno |
| WASD/Setas, botão do meio, roda | Câmera e zoom |
| `Ctrl+R` (ou `R` no fim) | Novo mapa |

## Trilha sonora
Todos os arquivos `.mp3/.ogg/.wav/.flac` em `assets/audio/music/` tocam em ordem alfabética,
em loop, com fade. Sem dispositivo de áudio ou com arquivo inválido, o jogo segue sem música.

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
3. **Zumbis** – enxames (1–10 por tile) seguem campo de fluxo Dijkstra até alvos civis/som, fundem-se ao se encontrarem.
4. **Defesas** – Balistas disparam automaticamente.
5. **Ataque/Infecção** – enxames atacam vizinhos; Tenda com HP 0 vira Casa Infectada que gera zumbis.
6. **Fim de rodada** – produção de ouro, ondas nas bordas, checagem de vitória.

## Estrutura
- `game/config.py` – balanceamento, custos, cores
- `game/grid.py` – `Grid`, `Tile`, `Terrain`, distâncias, BFS/Dijkstra
- `game/entities.py` – `Building` (CC, Tenda, Muro, Balista, Tesla, Casa Infectada), `Unit` (Soldado, Ranger), `ZombieSwarm`
- `game/world.py` – regras e simulação (sem pygame)
- `game/turns.py` – máquina de estados das fases
- `game/renderer.py` – câmera (offset/zoom) e desenho
- `game/hud.py` – painel lateral
- `game/fog.py` – névoa de guerra (visível/explorado)
- `game/audio.py` – player da trilha sonora
- `game/menu.py` – menu inicial/pausa e configurações
- `game/app.py` – loop principal e entrada
