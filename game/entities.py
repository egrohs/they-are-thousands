"""Entidades do jogo: construções, unidades do jogador e enxames zumbis."""
from __future__ import annotations

import itertools
import math
from typing import Optional

from .config import MAX_SWARM_SIZE
from .grid import Pos
from .stats import (BUILDING_STATS, HERO_SPECS, UNIT_SPECS, ZOMBIE_SPECS, BuildingStats,
                    HeroStats, ZombieSpec)


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
    _serials = itertools.count()

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
        self.garrison = stats.garrison           # abriga uma unidade no próprio tile
        self.range_bonus = stats.range_bonus
        self.vision_bonus = stats.vision_bonus
        self.harvest = stats.harvest             # "wood"/"stone": extrai do terreno ao redor
        self.serial = next(Building._serials)    # ordem de construção (prioridade nos tiles)
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


class Watchtower(Building):
    """Torre de Vigia: uma unidade entra (dividindo o tile) e ganha alcance, visão e proteção."""
    kind = "watchtower"
    color_key = "watchtower"


class Sawmill(Building):
    """Serraria: Madeira por turno conforme as Florestas no raio (como no They Are Billions)."""
    kind = "sawmill"
    color_key = "sawmill"


class Quarry(Building):
    """Extrator de Pedra: Pedra por turno conforme as Pedreiras no raio."""
    kind = "quarry"
    color_key = "quarry"


class InfectedHouse(Building):
    kind = "infected"
    hostile = True
    color_key = "infected"


BUILDING_TYPES: dict[str, type[Building]] = {
    "wall": Wall,
    "tent": Tent,
    "ballista": Ballista,
    "tesla": Tesla,
    "watchtower": Watchtower,
    "sawmill": Sawmill,
    "quarry": Quarry,
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


class Hero(Unit):
    """Herói controlado por um jogador (`owner`; 0 = sem dono, qualquer um controla).
    Stats base em `data/heroes.csv`; dano/HP/mana crescem por nível (XP).

    Estados: "active" (no mapa), "downed" (caído no tile por alguns turnos, hp 0,
    aguardando resgate) e "recovering" (capturado, fora do mapa, convalescendo na base)."""
    kind = "hero"

    def __init__(self, pos: Pos, hero_id: str, owner: int = 0):
        spec: HeroStats = HERO_SPECS[hero_id]
        self.spec = spec
        self.hero_id = hero_id
        self.name = spec.name
        self.role = spec.role
        self.symbol = spec.symbol
        self.color = spec.color
        self.color_key = "text"
        self.owner = owner
        Entity.__init__(self, pos, spec.hp)
        self.moved = False
        self.acted = False
        self.xp = 0
        self.level = 1
        self.mana = spec.mana
        self.cooldowns: dict[str, int] = {}
        self.state = "active"
        self.downed_turns = 0
        self.downed_fresh = False   # caiu neste turno: a contagem só começa no próximo
        self.recover_turns = 0
        self.debuff_turns = 0
        self.stealth_turns = 0
        self.guard_turns = 0
        self.guard_armor = 0
        self.kills = 0

    # --- atributos derivados do nível e de efeitos --------------------------
    @property
    def debuffed(self) -> bool:
        return self.debuff_turns > 0

    @property
    def move_range(self) -> int:
        return max(1, self.spec.move - (1 if self.debuffed else 0))

    @property
    def attack_range(self) -> int:
        return self.spec.attack_range

    @property
    def damage(self) -> int:
        base = self.spec.damage + self.spec.damage_per_level * (self.level - 1)
        return max(1, base - (1 if self.debuffed else 0))

    @property
    def noise(self) -> int:
        return self.spec.noise

    @property
    def vision(self) -> int:
        return self.spec.vision

    @property
    def armor(self) -> int:
        return self.spec.armor + self.guard_armor

    @property
    def max_mana(self) -> int:
        return self.spec.mana + self.spec.mana_per_level * (self.level - 1)

    @property
    def stealthed(self) -> bool:
        return self.stealth_turns > 0 and self.alive

    @property
    def downed(self) -> bool:
        return self.state == "downed"

    def take_damage(self, amount: int) -> int:
        return super().take_damage(max(1, amount - self.armor) if amount > 0 else 0)

    def cooldown(self, skill_id: str) -> int:
        return self.cooldowns.get(skill_id, 0)



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
        self.taunt_hero: Optional[str] = None  # herói que o provocou (persegue e ataca)
        self.taunt_turns = 0
        self.rooted_turns = 0              # preso por Raízes: não anda

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
