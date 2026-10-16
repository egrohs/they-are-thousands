"""Constantes de balanceamento, layout e cores."""
from __future__ import annotations

from dataclasses import dataclass

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
HQ_BUILD_RADIUS = 4         # território (Chebyshev) ao redor do Centro de Comando
TESLA_BUILD_RADIUS = 3      # território (Chebyshev) ao redor de cada Torre Tesla
MAX_SWARM_SIZE = 10
ZOMBIE_SPEED = 2            # passos por turno para enxames agressivos
AGGRO_DISTANCE = 7          # custo de caminho até alvo civil que desperta enxames ociosos
WALL_BASH_COST = 6          # custo de "atravessar" um muro/balista no pathfinding
FOREST_MOVE_COST = 2
NOISE_MEMORY_TURNS = 2
WANDER_CHANCE = 0.35
INFECTED_HP = 6
INFECTED_SPAWN = 2
HQ_HP = 20
HQ_GOLD_INCOME = 2

REPAIR_AP = 1
REPAIR_WOOD = 1
REPAIR_AMOUNT = 5
REPAIR_NOISE = 1

ATTACK_AP = 1
GATHER_AP = 1
GATHER_AMOUNT = 3
GATHER_NOISE = 2

BALLISTA_RANGE = 4
BALLISTA_DAMAGE = 3
BALLISTA_NOISE = 2

START_RESOURCES = {"gold": 10, "wood": 12, "stone": 4}
RESOURCE_LABELS = {"gold": "Ouro", "wood": "Madeira", "stone": "Pedra"}

# fim do turno N -> (quantidade de enxames, tamanho)
WAVES = {2: (2, 4), 4: (3, 5), 6: (3, 6), 8: (4, 6)}
FINAL_HORDE_TURN = 9
FINAL_HORDE = (8, 9)

PHASE_DELAY = 0.45  # segundos exibindo cada fase automática


@dataclass(frozen=True)
class BuildSpec:
    name: str
    symbol: str
    ap: int
    gold: int
    wood: int
    stone: int
    hp: int
    noise: int
    gold_income: int = 0

    @property
    def cost(self) -> dict[str, int]:
        return {"gold": self.gold, "wood": self.wood, "stone": self.stone}


@dataclass(frozen=True)
class UnitSpec:
    name: str
    symbol: str
    hp: int
    move: int
    attack_range: int
    damage: int
    noise: int


BUILD_SPECS: dict[str, BuildSpec] = {
    "wall": BuildSpec("Muro", "M", ap=1, gold=0, wood=2, stone=0, hp=10, noise=2),
    "tent": BuildSpec("Tenda", "T", ap=2, gold=4, wood=4, stone=0, hp=6, noise=2, gold_income=3),
    "ballista": BuildSpec("Balista", "B", ap=3, gold=6, wood=4, stone=3, hp=8, noise=4),
    "tesla": BuildSpec("Tesla", "E", ap=1, gold=3, wood=2, stone=0, hp=4, noise=1),
}

UNIT_SPECS: dict[str, UnitSpec] = {
    "soldier": UnitSpec("Soldado", "S", hp=7, move=3, attack_range=3, damage=4, noise=6),
    "ranger": UnitSpec("Ranger", "R", hp=5, move=4, attack_range=4, damage=2, noise=1),
}

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
    "territory": (120, 200, 255),
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
}
