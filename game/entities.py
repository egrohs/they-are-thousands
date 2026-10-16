"""Entidades do jogo: construções, unidades do jogador e enxames zumbis."""
from __future__ import annotations

import math
from typing import Optional

from .config import (BALLISTA_DAMAGE, BALLISTA_RANGE, BUILD_SPECS, HQ_GOLD_INCOME, HQ_HP,
                     INFECTED_HP, MAX_SWARM_SIZE, UNIT_SPECS)
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


class CommandCenter(Building):
    kind = "hq"
    name = "Centro de Comando"
    symbol = "CC"
    civil = True
    gold_income = HQ_GOLD_INCOME
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
    """Pilha de 1..MAX_SWARM_SIZE zumbis ocupando um único tile."""

    def __init__(self, pos: Pos, count: int, aggressive: bool = False):
        self.pos = pos
        self.count = max(1, min(MAX_SWARM_SIZE, count))
        self.aggressive = aggressive
        self.noise_target: Optional[Pos] = None
        self.noise_turns = 0
        self.intent: Optional[Pos] = None  # tile que o enxame quer atacar

    @property
    def alive(self) -> bool:
        return self.count > 0

    @property
    def space(self) -> int:
        return MAX_SWARM_SIZE - self.count

    @property
    def attack_power(self) -> int:
        return max(1, math.ceil(self.count / 2))

    def kill(self, amount: int) -> int:
        killed = min(self.count, max(0, amount))
        self.count -= killed
        return killed

    def alert(self, target: Pos, turns: int) -> None:
        self.aggressive = True
        self.noise_target = target
        self.noise_turns = turns
