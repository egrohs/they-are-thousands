"""Entidades do jogo: construções, unidades do jogador e enxames zumbis."""
from __future__ import annotations

import math
from typing import Optional

from .config import (BALLISTA_DAMAGE, BALLISTA_RANGE, BUILD_SPECS, HQ_BUILD_RADIUS,
                     HQ_GOLD_INCOME, HQ_HP, INFECTED_HP, MAX_SWARM_SIZE, TESLA_BUILD_RADIUS,
                     UNIT_SPECS, ZOMBIE_SPECS, ZombieSpec)
from .grid import Pos


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
    kind = "building"
    civil = False       # alvo prioritário dos zumbis (gera campo de atração)
    hostile = False     # pertence aos zumbis
    gold_income = 0
    build_radius = 0    # >0: expande o território construível


class CommandCenter(Building):
    kind = "hq"
    name = "Centro de Comando"
    symbol = "CC"
    civil = True
    gold_income = HQ_GOLD_INCOME
    build_radius = HQ_BUILD_RADIUS
    color_key = "hq"

    def __init__(self, pos: Pos):
        super().__init__(pos, HQ_HP)


class _SpecBuilding(Building):
    def __init__(self, pos: Pos):
        spec = BUILD_SPECS[self.kind]
        self.name = spec.name
        self.symbol = spec.symbol
        self.gold_income = spec.gold_income
        super().__init__(pos, spec.hp)


class Tent(_SpecBuilding):
    kind = "tent"
    civil = True
    color_key = "tent"


class Wall(_SpecBuilding):
    kind = "wall"
    color_key = "wall"


class Ballista(_SpecBuilding):
    kind = "ballista"
    color_key = "ballista"
    attack_range = BALLISTA_RANGE
    damage = BALLISTA_DAMAGE


class Tesla(_SpecBuilding):
    kind = "tesla"
    color_key = "tesla"
    build_radius = TESLA_BUILD_RADIUS


class InfectedHouse(Building):
    kind = "infected"
    name = "Casa Infectada"
    symbol = "X"
    hostile = True
    color_key = "infected"

    def __init__(self, pos: Pos):
        super().__init__(pos, INFECTED_HP)


BUILDING_TYPES: dict[str, type[_SpecBuilding]] = {
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
