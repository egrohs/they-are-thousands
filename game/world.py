"""Estado do jogo e regras: construção, ações de unidades, som, IA zumbi e infecção.

Esta camada não conhece pygame; é totalmente testável em modo headless.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from .config import (AGGRO_DISTANCE, AP_PER_TURN, ATTACK_AP, BALLISTA_NOISE, BUILD_SPECS,
                     HQ_BUILD_RADIUS, TESLA_BUILD_RADIUS, FINAL_HORDE, FINAL_HORDE_TURN, FOREST_MOVE_COST, GATHER_AMOUNT,
                     GATHER_AP, GATHER_NOISE, GRID_H, GRID_W, INFECTED_SPAWN, MAX_TURNS,
                     NOISE_MEMORY_TURNS, REPAIR_AMOUNT, REPAIR_AP, REPAIR_NOISE, REPAIR_WOOD,
                     RESOURCE_LABELS, START_RESOURCES, WALL_BASH_COST, WANDER_CHANCE, WAVES,
                     ZOMBIE_SPEED)
from .entities import (BUILDING_TYPES, Ballista, Building, CommandCenter, Entity, InfectedHouse,
                       Ranger, Soldier, Tent, Unit, ZombieSwarm)
from .grid import INF, Grid, Pos, Terrain

MAX_LOG = 80


@dataclass(frozen=True)
class NoiseEvent:
    pos: Pos
    radius: int
    source: str


@dataclass(frozen=True)
class Effect:
    start: Pos
    end: Pos
    color_key: str


class World:
    def __init__(self, seed: Optional[int] = None):
        self.seed = seed if seed is not None else random.randrange(1_000_000)
        self.rng = random.Random(self.seed)
        self.grid = Grid(GRID_W, GRID_H)
        self.resources: dict[str, int] = dict(START_RESOURCES)
        self.ap = AP_PER_TURN
        self.turn = 1
        self.log: list[str] = []
        self.pending_noise: list[NoiseEvent] = []
        self.active_noise: list[NoiseEvent] = []
        self.noise_map: dict[Pos, int] = {}
        self.effects: list[Effect] = []
        self.game_over = False
        self.victory = False
        self.final_horde_spawned = False
        self.zombies_killed = 0
        self.hq: CommandCenter
        self._generate_map()
        self.begin_player_phase()
        self.message(f"Semente do mapa: {self.seed}. Sobreviva {MAX_TURNS} turnos!")

    # ======================================================================
    # Utilidades
    # ======================================================================
    def message(self, text: str) -> None:
        self.log.append(f"T{self.turn}: {text}")
        if len(self.log) > MAX_LOG:
            del self.log[: len(self.log) - MAX_LOG]

    @property
    def total_zombies(self) -> int:
        return sum(s.count for s in self.grid.swarms())

    def infected_houses(self) -> list[InfectedHouse]:
        return [b for b in self.grid.buildings() if isinstance(b, InfectedHouse)]

    def _missing_resources(self, cost: dict[str, int]) -> str:
        missing = [f"{RESOURCE_LABELS[k]} {v - self.resources[k]}"
                   for k, v in cost.items() if v > self.resources[k]]
        return ", ".join(missing)

    def _spend(self, ap: int, cost: dict[str, int]) -> None:
        self.ap -= ap
        for k, v in cost.items():
            self.resources[k] -= v

    def emit_noise(self, pos: Pos, radius: int, source: str) -> None:
        if radius > 0:
            self.pending_noise.append(NoiseEvent(pos, radius, source))

    # ======================================================================
    # Geração de mapa
    # ======================================================================
    @property
    def center(self) -> Pos:
        return (GRID_W // 2, GRID_H // 2)

    def _random_pos(self, min_dist: int = 0, max_dist: int = 99) -> Pos:
        for _ in range(500):
            p = (self.rng.randrange(GRID_W), self.rng.randrange(GRID_H))
            if min_dist <= Grid.chebyshev(p, self.center) <= max_dist:
                return p
        return (0, 0)

    def _blob(self, start: Pos, size: int, terrain: Terrain, amount: tuple[int, int]) -> None:
        cells = {start}
        attempts = 0
        while len(cells) < size and attempts < size * 20:
            attempts += 1
            base = self.rng.choice(sorted(cells))
            n = self.rng.choice(self.grid.neighbors4(base))
            if Grid.chebyshev(n, self.center) > 3:
                cells.add(n)
        for p in cells:
            if Grid.chebyshev(p, self.center) <= 3:
                continue
            tile = self.grid.tile(p)
            tile.terrain = terrain
            tile.resource_amount = self.rng.randint(*amount) if terrain.resource else 0

    def _generate_map(self) -> None:
        self._blob(self._random_pos(7), self.rng.randint(8, 14), Terrain.WATER, (0, 0))
        self._blob(self._random_pos(4, 5), 5, Terrain.FOREST, (5, 9))
        self._blob(self._random_pos(4, 6), 4, Terrain.ROCK, (4, 8))
        for _ in range(4):
            self._blob(self._random_pos(5), self.rng.randint(4, 8), Terrain.FOREST, (5, 9))
        for _ in range(2):
            self._blob(self._random_pos(6), self.rng.randint(3, 5), Terrain.ROCK, (4, 8))

        cx, cy = self.center
        self.hq = CommandCenter((cx, cy))
        self.grid.place_building(self.hq)
        for pos in ((cx - 2, cy - 1), (cx + 2, cy + 1)):
            self.grid.place_building(Tent(pos))
        for unit in (Soldier((cx, cy + 2)), Ranger((cx - 1, cy - 2)), Ranger((cx + 1, cy - 2))):
            self.grid.place_unit(unit)

        placed = 0
        for _ in range(200):
            if placed >= 6:
                break
            p = self._random_pos(8)
            if self.grid.is_free(p):
                self.grid.place_swarm(ZombieSwarm(p, self.rng.randint(2, 5)))
                placed += 1

    # ======================================================================
    # Ações do jogador: construção / reparo
    # ======================================================================
    def build_anchors(self) -> list[Building]:
        return [b for b in self.grid.buildings()
                if b.alive and not b.hostile and b.build_radius > 0]

    def build_zone(self) -> set[Pos]:
        zone: set[Pos] = set()
        for b in self.build_anchors():
            zone.update(self.grid.tiles_in_radius(b.pos, b.build_radius, "chebyshev"))
        return zone

    def in_build_range(self, pos: Pos, zone: Optional[set[Pos]] = None) -> bool:
        return pos in (zone if zone is not None else self.build_zone())

    def can_build(self, kind: str, pos: Pos,
                  zone: Optional[set[Pos]] = None) -> tuple[bool, str]:
        if self.game_over:
            return False, "Jogo encerrado."
        spec = BUILD_SPECS.get(kind)
        if spec is None:
            return False, f"Construção desconhecida: {kind}"
        if not self.grid.in_bounds(pos):
            return False, "Fora do mapa."
        tile = self.grid.tile(pos)
        if not tile.terrain.buildable:
            return False, f"Não é possível construir em {tile.terrain.label}."
        if tile.occupied:
            return False, "Tile ocupado."
        if not self.in_build_range(pos, zone):
            return False, (f"Fora do território (raio {HQ_BUILD_RADIUS} do CC / "
                           f"{TESLA_BUILD_RADIUS} de Tesla). Construa uma Tesla para expandir.")
        if self.ap < spec.ap:
            return False, f"AP insuficiente ({spec.ap} necessário)."
        missing = self._missing_resources(spec.cost)
        if missing:
            return False, f"Faltam recursos: {missing}."
        return True, ""

    def build(self, kind: str, pos: Pos) -> bool:
        ok, reason = self.can_build(kind, pos)
        if not ok:
            self.message(reason)
            return False
        spec = BUILD_SPECS[kind]
        self._spend(spec.ap, spec.cost)
        self.grid.place_building(BUILDING_TYPES[kind](pos))
        self.emit_noise(pos, spec.noise, spec.name)
        self.message(f"{spec.name} construído(a) em {pos}.")
        return True

    def can_repair(self, pos: Pos) -> tuple[bool, str]:
        if self.game_over:
            return False, "Jogo encerrado."
        if not self.grid.in_bounds(pos):
            return False, "Fora do mapa."
        b = self.grid.tile(pos).building
        if b is None or b.hostile or not b.alive:
            return False, "Nenhuma construção aliada para reparar."
        if b.hp >= b.max_hp:
            return False, f"{b.name} já está com HP máximo."
        if self.ap < REPAIR_AP:
            return False, "AP insuficiente."
        if self.resources["wood"] < REPAIR_WOOD:
            return False, "Madeira insuficiente."
        return True, ""

    def repair(self, pos: Pos) -> bool:
        ok, reason = self.can_repair(pos)
        if not ok:
            self.message(reason)
            return False
        b = self.grid.tile(pos).building
        assert b is not None
        self._spend(REPAIR_AP, {"wood": REPAIR_WOOD})
        healed = b.heal(REPAIR_AMOUNT)
        self.emit_noise(pos, REPAIR_NOISE, "Reparo")
        self.message(f"{b.name} reparado(a) (+{healed} HP).")
        return True

    # ======================================================================
    # Ações do jogador: unidades
    # ======================================================================
    def _unit_passable(self, pos: Pos) -> bool:
        return self.grid.is_free(pos)

    def unit_moves(self, unit: Unit) -> dict[Pos, int]:
        if self.game_over or unit.moved or not unit.alive:
            return {}
        reach = self.grid.bfs_reachable(unit.pos, unit.move_range, self._unit_passable)
        reach.pop(unit.pos, None)
        return reach

    def move_unit(self, unit: Unit, dest: Pos) -> bool:
        if dest not in self.unit_moves(unit):
            self.message(f"{unit.name} não alcança {dest}.")
            return False
        self.grid.move_unit(unit, dest)
        unit.moved = True
        return True

    def attack_targets(self, unit: Unit) -> list[Pos]:
        if self.game_over or unit.acted or not unit.alive or self.ap < ATTACK_AP:
            return []
        targets = []
        for p in self.grid.tiles_in_radius(unit.pos, unit.attack_range, "chebyshev"):
            t = self.grid.tile(p)
            if t.swarm is not None or (t.building is not None and t.building.hostile):
                targets.append(p)
        return targets

    def unit_attack(self, unit: Unit, pos: Pos) -> bool:
        if pos not in self.attack_targets(unit):
            self.message(f"{unit.name} não pode atacar {pos}.")
            return False
        self.ap -= ATTACK_AP
        unit.acted = True
        tile = self.grid.tile(pos)
        if tile.swarm is not None:
            swarm = tile.swarm
            killed = swarm.kill(unit.damage)
            self.zombies_killed += killed
            self.message(f"{unit.name} abateu {killed} zumbi(s) em {pos}.")
            if not swarm.alive:
                self.grid.remove_swarm(swarm)
        elif tile.building is not None:
            house = tile.building
            dealt = house.take_damage(unit.damage)
            self.message(f"{unit.name} causou {dealt} de dano à {house.name}.")
            if not house.alive:
                self.grid.remove_building(house)
                self.message(f"{house.name} em {pos} destruída!")
        self.effects.append(Effect(unit.pos, pos, "shot"))
        self.emit_noise(unit.pos, unit.noise, unit.name)
        return True

    def gather_targets(self, unit: Unit) -> list[Pos]:
        if self.game_over or unit.acted or not unit.alive or self.ap < GATHER_AP:
            return []
        return [p for p in self.grid.tiles_in_radius(unit.pos, 1, "chebyshev")
                if self.grid.tile(p).terrain.resource and self.grid.tile(p).resource_amount > 0]

    def unit_gather(self, unit: Unit, pos: Pos) -> bool:
        if pos not in self.gather_targets(unit):
            self.message(f"{unit.name} não pode coletar em {pos}.")
            return False
        tile = self.grid.tile(pos)
        res = tile.terrain.resource
        assert res is not None
        amount = min(GATHER_AMOUNT, tile.resource_amount)
        tile.resource_amount -= amount
        self.resources[res] += amount
        self.ap -= GATHER_AP
        unit.acted = True
        self.emit_noise(pos, GATHER_NOISE, "Coleta")
        self.message(f"{unit.name} coletou +{amount} {RESOURCE_LABELS[res]}.")
        if tile.resource_amount <= 0:
            tile.terrain = Terrain.GRASS
            self.message(f"Depósito em {pos} esgotado.")
        return True

    # ======================================================================
    # Fases automáticas
    # ======================================================================
    def begin_player_phase(self) -> None:
        self.ap = AP_PER_TURN
        for u in self.grid.units():
            u.reset_turn()

    def propagate_noise(self) -> None:
        """Fase de som: transforma eventos pendentes em mapa de decibéis e alerta enxames."""
        self.effects.clear()
        events, self.pending_noise = self.pending_noise, []
        self.active_noise = events
        self.noise_map = {}
        for ev in events:
            for p in self.grid.tiles_in_radius(ev.pos, ev.radius, "manhattan"):
                level = ev.radius - Grid.manhattan(p, ev.pos) + 1
                if level > self.noise_map.get(p, 0):
                    self.noise_map[p] = level
        alerted = 0
        for swarm in self.grid.swarms():
            best: Optional[tuple[int, NoiseEvent]] = None
            for ev in events:
                d = Grid.manhattan(swarm.pos, ev.pos)
                if d <= ev.radius:
                    level = ev.radius - d + 1
                    if best is None or level > best[0]:
                        best = (level, ev)
            if best is not None:
                swarm.alert(best[1].pos, NOISE_MEMORY_TURNS)
                alerted += 1
        if events:
            self.message(f"Barulho de {len(events)} fonte(s) atraiu {alerted} enxame(s).")

    def _zombie_enter_cost(self, pos: Pos) -> Optional[float]:
        tile = self.grid.tile(pos)
        if not tile.terrain.passable:
            return None
        b = tile.building
        if b is not None:
            if b.hostile:
                return None
            if not b.civil:
                return float(WALL_BASH_COST)
        if tile.terrain is Terrain.FOREST:
            return float(FOREST_MOVE_COST)
        return 1.0

    def civil_field(self) -> dict[Pos, float]:
        goals = [b.pos for b in self.grid.buildings() if b.civil and b.alive]
        goals += [u.pos for u in self.grid.units() if u.alive]
        return self.grid.dijkstra(goals, self._zombie_enter_cost)

    def _field_for(self, swarm: ZombieSwarm, civil: dict[Pos, float],
                   cache: dict[Pos, dict[Pos, float]]) -> dict[Pos, float]:
        target = swarm.noise_target
        if target is None:
            return civil
        if Grid.manhattan(swarm.pos, target) <= 1:
            swarm.noise_target = None
            swarm.noise_turns = 0
            return civil
        if target not in cache:
            cache[target] = self.grid.dijkstra([target], self._zombie_enter_cost)
        return cache[target]

    def _step_swarm(self, swarm: ZombieSwarm, field: dict[Pos, float]) -> bool:
        """Move um passo seguindo o campo. Retorna True se ainda pode continuar andando."""
        current = field.get(swarm.pos, INF)
        candidates = sorted((field[n], n) for n in self.grid.neighbors4(swarm.pos)
                            if n in field and field[n] < current)
        for _, n in candidates:
            tile = self.grid.tile(n)
            if tile.unit is not None or (tile.building is not None and not tile.building.hostile):
                swarm.intent = n
                return False
            if tile.swarm is not None:
                other = tile.swarm
                if other.space <= 0:
                    continue
                moved = min(other.space, swarm.count)
                other.count += moved
                swarm.count -= moved
                other.aggressive = other.aggressive or swarm.aggressive
                if swarm.count <= 0:
                    self.grid.remove_swarm(swarm)
                return False
            if not self.grid.is_free(n):
                continue
            self.grid.move_swarm(swarm, n)
            return True
        return False

    def _wander(self, swarm: ZombieSwarm) -> None:
        if self.rng.random() >= WANDER_CHANCE:
            return
        options = [n for n in self.grid.neighbors4(swarm.pos) if self.grid.is_free(n)]
        if options:
            self.grid.move_swarm(swarm, self.rng.choice(options))

    def zombies_move(self) -> None:
        civil = self.civil_field()
        cache: dict[Pos, dict[Pos, float]] = {}
        swarms = self.grid.swarms()
        for s in swarms:
            s.intent = None
            if not s.aggressive and civil.get(s.pos, INF) <= AGGRO_DISTANCE:
                s.aggressive = True
        swarms.sort(key=lambda s: (self._field_for(s, civil, cache).get(s.pos, INF), s.pos))
        for s in swarms:
            if s.count <= 0 or self.grid.tile(s.pos).swarm is not s:
                continue
            if not s.aggressive:
                self._wander(s)
                continue
            for _ in range(ZOMBIE_SPEED):
                field = self._field_for(s, civil, cache)
                if not self._step_swarm(s, field):
                    break

    def ballistas_fire(self) -> None:
        ballistas = sorted((b for b in self.grid.buildings()
                            if isinstance(b, Ballista) and b.alive), key=lambda b: b.pos)
        for b in ballistas:
            in_range = [s for s in self.grid.swarms()
                        if Grid.chebyshev(b.pos, s.pos) <= b.attack_range]
            if not in_range:
                continue
            target = min(in_range, key=lambda s: (Grid.chebyshev(b.pos, s.pos), -s.count, s.pos))
            killed = target.kill(b.damage)
            self.zombies_killed += killed
            self.effects.append(Effect(b.pos, target.pos, "bolt"))
            self.emit_noise(b.pos, BALLISTA_NOISE, b.name)
            self.message(f"Balista em {b.pos} abateu {killed} zumbi(s).")
            if not target.alive:
                self.grid.remove_swarm(target)

    def _attack_priority(self, e: Entity) -> tuple:
        if isinstance(e, Unit):
            group = 0
        elif isinstance(e, Building) and e.civil:
            group = 1
        else:
            group = 2
        return (group, e.hp, e.pos)

    def zombies_attack(self) -> None:
        for s in sorted(self.grid.swarms(), key=lambda s: s.pos):
            if not s.alive:
                continue
            targets: list[Entity] = []
            for n in self.grid.neighbors4(s.pos):
                t = self.grid.tile(n)
                if t.unit is not None and t.unit.alive:
                    targets.append(t.unit)
                elif t.building is not None and not t.building.hostile and t.building.alive:
                    targets.append(t.building)
            if not targets:
                continue
            target = next((e for e in targets if e.pos == s.intent), None)
            if target is None:
                target = min(targets, key=self._attack_priority)
            dealt = target.take_damage(s.attack_power)
            self.effects.append(Effect(s.pos, target.pos, "bite"))
            if target.alive:
                self.message(f"Enxame ({s.count}) causou {dealt} de dano em {target.name}.")
            else:
                self._on_destroyed(target, s)

    def _on_destroyed(self, target: Entity, attacker: ZombieSwarm) -> None:
        if isinstance(target, Unit):
            self.grid.remove_unit(target)
            if attacker.space > 0:
                attacker.count += 1
            self.message(f"{target.name} foi devorado e se juntou ao enxame!")
        elif isinstance(target, Tent):
            self.message(f"Tenda em {target.pos} caiu! A infecção se espalha...")
        elif isinstance(target, CommandCenter):
            self.message("O Centro de Comando foi destruído!")
            self.check_defeat()
        elif isinstance(target, Building):
            self.grid.remove_building(target)
            self.message(f"{target.name} em {target.pos} foi destruído(a).")

    def resolve_infection(self) -> None:
        for b in self.grid.buildings():
            if isinstance(b, Tent) and not b.alive:
                self.grid.remove_building(b)
                self.grid.place_building(InfectedHouse(b.pos))
                self.message(f"Tenda em {b.pos} virou Casa Infectada!")
        for house in self.infected_houses():
            spawned = self._spawn_near(house.pos, INFECTED_SPAWN)
            if spawned:
                self.message(f"Casa Infectada em {house.pos} gerou {spawned} zumbi(s).")

    def _spawn_near(self, pos: Pos, amount: int) -> int:
        remaining = amount
        for n in self.grid.neighbors4(pos):
            if remaining <= 0:
                break
            tile = self.grid.tile(n)
            if tile.swarm is not None and tile.swarm.space > 0:
                add = min(tile.swarm.space, remaining)
                tile.swarm.count += add
                tile.swarm.aggressive = True
                remaining -= add
            elif self.grid.is_free(n):
                swarm = ZombieSwarm(n, remaining, aggressive=True)
                self.grid.place_swarm(swarm)
                remaining -= swarm.count
        return amount - remaining

    def _spawn_wave(self, swarms: int, size: int) -> int:
        spawned = 0
        for i in range(swarms):
            side = i % 4
            for _ in range(60):
                k = self.rng.randrange(GRID_W if side in (0, 1) else GRID_H)
                pos = {0: (k, 0), 1: (k, GRID_H - 1), 2: (0, k), 3: (GRID_W - 1, k)}[side]
                if self.grid.is_free(pos):
                    self.grid.place_swarm(ZombieSwarm(pos, size, aggressive=True))
                    spawned += 1
                    break
        return spawned

    def end_round(self) -> None:
        """Cleanup: produção, memória de som, ondas e condição de vitória."""
        income = sum(b.gold_income for b in self.grid.buildings() if b.alive and not b.hostile)
        self.resources["gold"] += income
        self.message(f"Colônia produziu +{income} Ouro.")
        for s in self.grid.swarms():
            if s.noise_turns > 0:
                s.noise_turns -= 1
                if s.noise_turns == 0:
                    s.noise_target = None
        if self.turn in WAVES:
            n = self._spawn_wave(*WAVES[self.turn])
            self.message(f"Uma onda de {n} enxame(s) surge nas bordas!")
        if self.turn == FINAL_HORDE_TURN:
            n = self._spawn_wave(*FINAL_HORDE)
            self.final_horde_spawned = True
            self.message(f"A HORDA FINAL chegou: {n} enxames!")

        if self.check_defeat():
            return
        if self.turn >= MAX_TURNS:
            self._finish(True, f"Vitória! A colônia sobreviveu {MAX_TURNS} turnos.")
        elif self.final_horde_spawned and not self.grid.swarms() and not self.infected_houses():
            self._finish(True, "Vitória! A horda final foi repelida.")
        else:
            self.turn += 1

    def check_defeat(self) -> bool:
        if not self.game_over and not self.hq.alive:
            self._finish(False, "Derrota! O Centro de Comando caiu.")
        return self.game_over and not self.victory

    def _finish(self, victory: bool, text: str) -> None:
        self.game_over = True
        self.victory = victory
        self.message(text)
