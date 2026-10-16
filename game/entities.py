"""Entidades do jogo: construções, unidades do jogador e enxames zumbis."""
from __future__ import annotations

import math
from typing import Optional

from .config import MAX_SWARM_SIZE
from .grid import Pos
from .stats import BUILDING_STATS, UNIT_SPECS, ZOMBIE_SPECS, BuildingStats, ZombieSpec


class Entity:
    name = "Entidade"
    symbol = "?"
    color_key = "text"

    def __init__(self, pos: Pos, max_hp: int):
        self.pos = pos
        self.max_hp = max_hp
        self.hp = max_hp

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def take_damage(self, amount: int) -> int:
        dealt = min(self.hp, max(0, amount))
        self.hp -= dealt
        return dealt

    def heal(self, amount: int) -> int:
        healed = min(self.max_hp - self.hp, max(0, amount))
        self.hp += healed
        return healed


# --- Construções -------------------------------------------------------------
class Building(Entity):
    """Construção; atributos numéricos vêm de `data/buildings.csv` (linha `kind`)."""
    kind = "building"
    civil = False       # alvo prioritário dos zumbis (gera campo de atração)
    hostile = False     # pertence aos zumbis

    def __init__(self, pos: Pos):
        stats: BuildingStats = BUILDING_STATS[self.kind]
        self.stats = stats
        self.name = stats.name
        self.symbol = stats.symbol
        self.gold_income = stats.gold_income
        self.build_radius = stats.build_radius   # >0: expande o território construível
        self.attack_range = stats.attack_range   # >0: dispara automaticamente
        self.damage = stats.damage
        self.vision = stats.vision
        super().__init__(pos, stats.hp)


class CommandCenter(Building):
    kind = "hq"
    civil = True
    color_key = "hq"


class Tent(Building):
    kind = "tent"
    civil = True
    color_key = "tent"


class Wall(Building):
    kind = "wall"
    color_key = "wall"


class Ballista(Building):
    kind = "ballista"
    color_key = "ballista"


class Tesla(Building):
    kind = "tesla"
    color_key = "tesla"


class InfectedHouse(Building):
    kind = "infected"
    hostile = True
    color_key = "infected"


BUILDING_TYPES: dict[str, type[Building]] = {
    "wall": Wall,
    "tent": Tent,
    "ballista": Ballista,
    "tesla": Tesla,
}


# --- Unidades ----------------------------------------------------------------
class Unit(Entity):
    kind = "unit"

    def __init__(self, pos: Pos):
        spec = UNIT_SPECS[self.kind]
        self.name = spec.name
        self.symbol = spec.symbol
        self.move_range = spec.move
        self.attack_range = spec.attack_range
        self.damage = spec.damage
        self.noise = spec.noise
        self.vision = spec.vision
        self.color_key = self.kind
        super().__init__(pos, spec.hp)
        self.moved = False
        self.acted = False

    def reset_turn(self) -> None:
        self.moved = False
        self.acted = False

    @property
    def exhausted(self) -> bool:
        return self.moved and self.acted


class Soldier(Unit):
    kind = "soldier"


class Ranger(Unit):
    kind = "ranger"


# --- Zumbis ------------------------------------------------------------------
class ZombieSwarm:
    """Pilha de 1..max_stack zumbis do mesmo tipo ocupando um único tile."""

    def __init__(self, pos: Pos, count: int, aggressive: bool = False, kind: str = "walker"):
        self.pos = pos
        self.kind = kind
        self.spec: ZombieSpec = ZOMBIE_SPECS[kind]
        self.count = max(1, min(self.max_stack, count))
        self.wounds = 0  # dano acumulado no zumbi da frente (tipos com HP > 1)
        self.aggressive = aggressive
        self.noise_target: Optional[Pos] = None
        self.noise_turns = 0
        self.intent: Optional[Pos] = None  # tile que o enxame quer atacar

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def max_stack(self) -> int:
        return min(MAX_SWARM_SIZE, self.spec.max_stack)

    @property
    def speed(self) -> int:
        return self.spec.speed

    @property
    def attack_range(self) -> int:
        return self.spec.attack_range

    @property
    def flying(self) -> bool:
        return self.spec.flying

    @property
    def alive(self) -> bool:
        return self.count > 0

    @property
    def space(self) -> int:
        return max(0, self.max_stack - self.count)

    @property
    def attack_power(self) -> int:
        return max(1, math.ceil(self.count * self.spec.attack))

    def damage_against(self, target_is_structure: bool) -> int:
        mult = self.spec.structure_mult if target_is_structure else 1.0
        return max(1, math.ceil(self.attack_power * mult))

    def can_merge(self, other: "ZombieSwarm") -> bool:
        return other.kind == self.kind and other.space > 0

    def kill(self, damage: int) -> int:
        """Aplica dano; retorna quantos zumbis morreram."""
        total = self.wounds + max(0, damage)
        killed = min(self.count, total // self.spec.hp)
        self.count -= killed
        self.wounds = 0 if self.count == 0 else total - killed * self.spec.hp
        return killed

    def alert(self, target: Pos, turns: int) -> None:
        self.aggressive = True
        self.noise_target = target
        self.noise_turns = turns
