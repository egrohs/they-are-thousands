"""Constantes de regras gerais, layout e cores.

Stats de construções, unidades e zumbis ficam nos CSVs de `data/` (ver `game/stats.py`).
"""
from __future__ import annotations

from pathlib import Path

# --- Áudio ------------------------------------------------------------------
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
MUSIC_DIR = ASSETS_DIR / "audio" / "music"
MUSIC_EXTENSIONS = {".mp3", ".ogg", ".wav", ".flac"}
MUSIC_VOLUME_DEFAULT = 0.5
MUSIC_VOLUME_STEP = 0.1
MUSIC_FADE_MS = 1500

# --- Dados de balanceamento (CSV) -------------------------------------------
DATA_DIR = ASSETS_DIR.parent / "data"

# --- Mapas personalizados -----------------------------------------------------
MAPS_DIR = ASSETS_DIR.parent / "maps"

# --- Sprites ----------------------------------------------------------------
IMAGES_DIR = ASSETS_DIR / "images"
# chave -> (arquivo, âncora vertical do recorte: 0 = topo, 0.5 = centro)
SPRITE_FILES: dict[str, tuple[str, float]] = {
    "ranger": ("ranger.png", 0.15),
    "tent": ("tend.png", 0.5),
    "infected": ("tend.png", 0.5),
    "zombie_runner": ("runner.png", 0.2),
    "zombie_walker": ("zombie.png", 0.15),
    "zombie_brute": ("executor.png", 0.2),
    "zombie_harpy": ("runner.png", 0.2),
    "zombie_venom": ("zombie.png", 0.15),
}
INFECTED_TINT = (140, 230, 110)
# tipos sem arte própria reaproveitam uma imagem com tingimento
ZOMBIE_TINTS = {"harpy": (205, 150, 255), "venom": (165, 255, 110)}
EXHAUSTED_TINT = (120, 120, 120)

# --- Grade / Janela -------------------------------------------------------
GRID_W = 24
GRID_H = 24
TILE_SIZE = 32

WINDOW_W = 1140
WINDOW_H = 800
HUD_W = 360
VIEW_W = WINDOW_W - HUD_W
VIEW_H = WINDOW_H
FPS = 60
CAMERA_PAN_SPEED = 600  # px/s

# --- Regras gerais --------------------------------------------------------
MAX_TURNS = 15
AP_PER_TURN = 6
MAX_SWARM_SIZE = 10         # limite absoluto; cada tipo tem seu próprio `max_stack`
AGGRO_DISTANCE = 7          # custo de caminho até alvo civil que desperta enxames ociosos
WALL_BASH_COST = 6          # custo de "atravessar" um muro/balista no pathfinding
NOISE_MEMORY_TURNS = 2
WANDER_CHANCE = 0.35

REPAIR_AP = 1
REPAIR_WOOD = 1
REPAIR_AMOUNT = 5
REPAIR_NOISE = 1

ATTACK_AP = 1
GATHER_AP = 1
GATHER_AMOUNT = 3
GATHER_NOISE = 2

START_RESOURCES = {"gold": 10, "wood": 12, "stone": 4}
RESOURCE_LABELS = {"gold": "Ouro", "wood": "Madeira", "stone": "Pedra"}

# ondas programadas: cronograma em data/waves.csv
WAVE_EDGE_SPREAD = 4    # ponto de entrada da onda: ±N tiles ao longo da borda anunciada
WAVE_EDGE_DEPTH = 2     # profundidade (tiles a partir da borda) usada para posicionar enxames
WAVE_WARNING_TURNS = 3  # o indicador no mapa aparece a partir de N turnos antes
# tipos dos enxames iniciais espalhados pelo mapa (sorteio ponderado)
START_SWARM_TYPES = (("walker", 4), ("runner", 1))

# névoa: tiles explorados só ficam na memória (terreno/construções/caixas) até
# visão + FOG_MEMORY_MARGIN tiles de alguma unidade/construção aliada; além disso, escuridão total
FOG_MEMORY_MARGIN = 3

UNDO_LIMIT = 30         # ações do jogador que podem ser desfeitas por turno

# caixas de recursos (tipos em data/crates.csv): espalhadas fora da base nos mapas aleatórios
CRATE_COUNT = 7
CRATE_SPACING = 3       # distância Chebyshev mínima entre caixas

PHASE_DELAY = 0.45  # segundos exibindo cada fase automática

# --- Névoa de guerra --------------------------------------------------------
FOW_ENABLED_DEFAULT = True  # raios de visão: coluna `vision` dos CSVs

COLORS: dict[str, tuple[int, int, int]] = {
    "bg": (16, 16, 20),
    "grid_line": (0, 0, 0),
    "grass": (62, 100, 56),
    "forest": (28, 66, 34),
    "rock": (104, 104, 112),
    "water": (38, 76, 136),
    "tree": (16, 44, 20),
    "stone_icon": (160, 160, 168),
    "hud_bg": (26, 26, 32),
    "hud_border": (70, 70, 82),
    "text": (232, 232, 232),
    "text_dim": (150, 150, 162),
    "title": (255, 120, 90),
    "gold": (240, 200, 60),
    "wood": (190, 135, 80),
    "stone": (185, 185, 195),
    "ap": (100, 185, 255),
    "hq": (70, 110, 210),
    "tent": (222, 192, 122),
    "wall": (138, 128, 118),
    "ballista": (168, 96, 44),
    "tesla": (90, 210, 230),
    "watchtower": (150, 110, 70),
    "sawmill": (185, 125, 60),
    "quarry": (125, 130, 150),
    "harvest": (250, 235, 150),
    "territory": (120, 200, 255),
    "fog_unexplored": (6, 6, 9),
    "fog_explored": (10, 10, 18),
    "fog_dark": (17, 17, 26),
    "menu_bg": (12, 12, 16),
    "infected": (120, 180, 40),
    "soldier": (60, 140, 235),
    "ranger": (80, 205, 145),
    "zombie_idle": (105, 36, 36),
    "zombie_aggr": (200, 40, 32),
    "zombie_noise": (255, 150, 40),
    "move": (80, 160, 255),
    "attack": (255, 60, 60),
    "gather": (240, 200, 60),
    "build_ok": (120, 235, 120),
    "build_bad": (235, 80, 80),
    "noise": (255, 225, 60),
    "select": (255, 255, 255),
    "hover": (255, 255, 160),
    "shot": (255, 240, 120),
    "bite": (255, 40, 40),
    "spit": (150, 230, 60),
    "bolt": (255, 160, 60),
    "button": (54, 54, 70),
    "button_hover": (76, 76, 98),
    "button_active": (92, 128, 62),
    "button_disabled": (38, 38, 44),
    "end_turn": (150, 60, 50),
    "hp_bg": (50, 10, 10),
    "hp_fg": (80, 220, 80),
    "hp_low": (230, 90, 50),
    "victory": (110, 230, 120),
    "defeat": (240, 70, 60),
    "wave_warning": (255, 110, 70),
}
