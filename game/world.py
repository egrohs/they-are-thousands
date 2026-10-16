"""Estado do jogo e regras: construção, ações de unidades, som, IA zumbi e infecção.

Esta camada não conhece pygame; é totalmente testável em modo headless.
"""
from __future__ import annotations

import copy
import functools
import random
from dataclasses import dataclass
from typing import Optional

from .config import (AGGRO_DISTANCE, AP_PER_TURN, ATTACK_AP,
                     FOW_ENABLED_DEFAULT, GATHER_AMOUNT,
                     GATHER_AP, GATHER_NOISE, GRID_H, GRID_W, MAX_TURNS,
                     NOISE_MEMORY_TURNS, REPAIR_AMOUNT, REPAIR_AP, REPAIR_NOISE, REPAIR_WOOD,
                     RESOURCE_LABELS, START_RESOURCES, START_SWARM_TYPES, WALL_BASH_COST,
                     WANDER_CHANCE, WAVE_EDGE_DEPTH, WAVE_EDGE_SPREAD, CRATE_COUNT, CRATE_SPACING,
                     UNDO_LIMIT)
from .entities import (BUILDING_TYPES, Building, CommandCenter, Entity, InfectedHouse,
                       Ranger, Soldier, Tent, Unit, ZombieSwarm)
from .fog import FogOfWar
from .grid import INF, Grid, Pos, Terrain
from .stats import (BUILD_SPECS, BUILDING_STATS, CRATE_SPECS, DIRECTION_NAMES, WAVE_SCHEDULE,
                    ZOMBIE_SPECS, WaveRow, direction_token)

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


@dataclass(frozen=True)
class WaveGroup:
    side: int      # 0 = norte, 1 = sul, 2 = oeste, 3 = leste
    anchor: Pos    # tile da borda em torno do qual os enxames entram
    kind: str
    swarms: int
    size: int

    @property
    def direction(self) -> str:
        return DIRECTION_NAMES[self.side]


@dataclass
class PlannedWave:
    turn: int
    final: bool
    groups: list[WaveGroup]
    spawned: bool = False

    @property
    def zombies(self) -> int:
        return sum(g.swarms * min(g.size, ZOMBIE_SPECS[g.kind].max_stack) for g in self.groups)

    @property
    def entry_points(self) -> list[tuple[int, Pos]]:
        """(lado, âncora) distintos da onda, na ordem do CSV."""
        seen: list[tuple[int, Pos]] = []
        for g in self.groups:
            if (g.side, g.anchor) not in seen:
                seen.append((g.side, g.anchor))
        return seen

    @property
    def directions(self) -> str:
        return " e ".join(DIRECTION_NAMES[side] for side, _ in self.entry_points)


def edge_pos(side: int, along: int, depth: int = 0) -> Pos:
    return {0: (along, depth), 1: (along, GRID_H - 1 - depth),
            2: (depth, along), 3: (GRID_W - 1 - depth, along)}[side]


def undoable(action):
    """Ação do jogador que pode ser desfeita. Guarda um snapshot antes; se a ação revelar
    informação nova (névoa explorada, zumbis avistados, emboscada), o histórico é travado,
    como em Into the Breach: não se pode voltar atrás depois de ver algo novo."""
    @functools.wraps(action)
    def wrapper(self: "World", *args, **kwargs):
        snapshot = self._snapshot()
        before = self._observation()
        self._revealed = False
        done = action(self, *args, **kwargs)
        if done:
            if self._revealed or self._observation_grew(before):
                if self.history:
                    self.message("Nova informação revelada: ações anteriores não podem mais "
                                 "ser desfeitas.")
                self.history.clear()
            else:
                self.history.append(snapshot)
                del self.history[:-UNDO_LIMIT]
        return done
    return wrapper


class World:
    def __init__(self, seed: Optional[int] = None, fog_enabled: bool = FOW_ENABLED_DEFAULT,
                 map_data: Optional[dict] = None):
        self.seed = seed if seed is not None else random.randrange(1_000_000)
        self.rng = random.Random(self.seed)
        self.map_name: Optional[str] = None
        if map_data is not None:
            from .maps import build_grid  # import local: maps depende de entities/grid
            self.grid, self.hq = build_grid(map_data)
            self.map_name = str(map_data.get("name", "Personalizado"))
        else:
            self.grid = Grid(GRID_W, GRID_H)
        self.fog = FogOfWar(self.grid, fog_enabled)
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
        self.crates_found = 0
        self.history: list[dict] = []   # snapshots para desfazer (só no turno atual)
        self._revealed = False
        if map_data is None:
            self._generate_map()
            self._place_crates()
        self.crates_total = sum(1 for t in self.grid if t.crate)
        self.waves = self._plan_waves(WAVE_SCHEDULE)
        self.begin_player_phase()
        if self.map_name:
            self.message(f"Mapa: {self.map_name}. Sobreviva {MAX_TURNS} turnos!")
        else:
            self.message(f"Semente do mapa: {self.seed}. Sobreviva {MAX_TURNS} turnos!")
        self._announce_next_wave()

    # ======================================================================
    # Desfazer
    # ======================================================================
    def _snapshot(self) -> dict:
        state = {k: v for k, v in self.__dict__.items() if k != "history"}
        return copy.deepcopy(state)

    def _observation(self) -> tuple[int, set[Pos]]:
        # posições (não id()): o resultado precisa ser idêntico em todos os jogadores do co-op
        if not self.fog.enabled:
            return 0, set()
        seen = {s.pos for s in self.grid.swarms() if self.fog.is_visible(s.pos)}
        return len(self.fog.explored), seen

    def _observation_grew(self, before: tuple[int, set[Pos]]) -> bool:
        explored, seen = self._observation()
        return explored > before[0] or bool(seen - before[1])

    @property
    def can_undo(self) -> bool:
        return bool(self.history) and not self.game_over

    def undo(self) -> bool:
        """Restaura o estado anterior à última ação do jogador neste turno.
        O objeto World é mantido (referências externas continuam válidas), mas
        construções/unidades são novas instâncias: seleções da UI devem ser limpas."""
        if not self.can_undo:
            self.message("Nada para desfazer.")
            return False
        history = self.history
        state = history.pop()
        self.__dict__.clear()
        self.__dict__.update(state)
        self.history = history
        self.message(f"Ação desfeita ({len(history)} restante(s)).")
        return True

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

    @property
    def visible_zombies(self) -> int:
        return sum(s.count for s in self.grid.swarms() if self.fog.is_visible(s.pos))

    def update_fog(self) -> None:
        self.fog.update()

    def shelter_of(self, unit: Unit) -> Optional[Building]:
        """Torre de Vigia que abriga a unidade (mesmo tile), se houver."""
        b = self.grid.tile(unit.pos).building
        return b if b is not None and b.garrison and b.alive else None

    def garrisoned(self, building: Building) -> Optional[Unit]:
        if not building.garrison:
            return None
        return self.grid.tile(building.pos).unit

    def unit_range(self, unit: Unit) -> int:
        shelter = self.shelter_of(unit)
        return unit.attack_range + (shelter.range_bonus if shelter else 0)

    def _can_enter_shelter(self, pos: Pos) -> bool:
        if not self.fog.is_known(pos):
            return False
        tile = self.grid.tile(pos)
        b = tile.building
        return (b is not None and b.garrison and b.alive and not b.hostile and tile.unit is None
                and tile.swarm is None)

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

    def _fill_isolated_pockets(self) -> None:
        """Terreno bloqueia movimento: bolsões de Campo sem acesso ao centro viram Floresta,
        para que nenhuma unidade/enxame nasça preso."""
        reach = self.grid.bfs_reachable(self.center, GRID_W * GRID_H,
                                        lambda p: self.grid.tile(p).terrain.passable)
        for t in self.grid:
            if t.terrain.passable and t.pos not in reach:
                t.terrain, t.resource_amount = Terrain.FOREST, self.rng.randint(5, 9)

    def _generate_map(self) -> None:
        self._blob(self._random_pos(7), self.rng.randint(8, 14), Terrain.WATER, (0, 0))
        self._blob(self._random_pos(4, 5), 5, Terrain.FOREST, (5, 9))
        self._blob(self._random_pos(4, 6), 4, Terrain.ROCK, (4, 8))
        for _ in range(4):
            self._blob(self._random_pos(5), self.rng.randint(4, 8), Terrain.FOREST, (5, 9))
        for _ in range(2):
            self._blob(self._random_pos(6), self.rng.randint(3, 5), Terrain.ROCK, (4, 8))
        self._fill_isolated_pockets()

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
                kinds, weights = zip(*START_SWARM_TYPES)
                kind = self.rng.choices(kinds, weights)[0]
                self.grid.place_swarm(ZombieSwarm(p, self.rng.randint(2, 5), kind=kind))
                placed += 1

    # ======================================================================
    # Produção: Serrarias / Extratores de Pedra
    # ======================================================================
    def _harvest_area(self, kind: str, pos: Pos) -> list[Pos]:
        spec = BUILDING_STATS[kind]
        return [p for p in self.grid.tiles_in_radius(pos, spec.harvest_radius, "chebyshev")
                if self.grid.tile(p).terrain.resource == spec.harvest]

    def harvest_claims(self) -> dict[Building, list[Pos]]:
        """Tiles explorados por cada extrator. Cada tile conta para um único extrator do mesmo
        recurso (o mais antigo), como no original: sobrepor áreas não duplica a produção."""
        claimed: set[tuple[str, Pos]] = set()
        claims: dict[Building, list[Pos]] = {}
        harvesters = sorted((b for b in self.grid.buildings()
                             if b.harvest and b.alive and not b.hostile), key=lambda b: b.serial)
        for b in harvesters:
            tiles = [p for p in self._harvest_area(b.kind, b.pos) if (b.harvest, p) not in claimed]
            claimed.update((b.harvest, p) for p in tiles)
            claims[b] = tiles
        return claims

    @staticmethod
    def harvest_yield(kind: str, tiles: int) -> int:
        spec = BUILDING_STATS[kind]
        return min(spec.harvest_max, tiles // spec.harvest_tiles) if spec.harvest else 0

    def harvest_preview(self, kind: str, pos: Pos) -> tuple[list[Pos], int]:
        """Tiles livres e produção/turno de um extrator novo em `pos` (não conta os já usados)."""
        spec = BUILDING_STATS[kind]
        taken = {p for b, tiles in self.harvest_claims().items() if b.harvest == spec.harvest
                 for p in tiles}
        tiles = [p for p in self._harvest_area(kind, pos) if p not in taken]
        return tiles, self.harvest_yield(kind, len(tiles))

    def production(self) -> dict[str, int]:
        """Produção por fim de turno (ouro das Tendas/CC + extratores)."""
        prod = {"gold": 0, "wood": 0, "stone": 0}
        for b in self.grid.buildings():
            if b.alive and not b.hostile:
                prod["gold"] += b.gold_income
        for b, tiles in self.harvest_claims().items():
            prod[b.harvest] += self.harvest_yield(b.kind, len(tiles))
        return prod

    def _place_crates(self) -> None:
        """Espalha caixas de recursos com RNG próprio (não altera o mapa nem a IA)."""
        rng = random.Random(self.seed * 7_919 + 13)
        kinds = [k for k, c in CRATE_SPECS.items() if c.weight > 0]
        if not kinds:
            return
        weights = [CRATE_SPECS[k].weight for k in kinds]
        placed: list[Pos] = []
        cells = [t.pos for t in self.grid if t.terrain.passable]
        for _ in range(CRATE_COUNT):
            kind = rng.choices(kinds, weights)[0]
            spec = CRATE_SPECS[kind]
            options = [p for p in cells if Grid.chebyshev(p, self.center) >= spec.min_dist
                       and self.grid.is_free(p) and not self.grid.tile(p).crate
                       and all(Grid.chebyshev(p, q) >= CRATE_SPACING for q in placed)]
            if not options:
                continue
            p = rng.choice(options)
            self.grid.tile(p).crate = kind
            placed.append(p)

    @staticmethod
    def loot_text(kind: str) -> str:
        return ", ".join(f"+{v} {RESOURCE_LABELS[k]}" for k, v in CRATE_SPECS[kind].loot.items())

    def collect_crate(self, pos: Pos, who: str) -> bool:
        """Abre a caixa em `pos` (se houver): recursos entram no estoque na hora."""
        tile = self.grid.tile(pos)
        kind = tile.crate
        if kind is None:
            return False
        tile.crate = None
        spec = CRATE_SPECS.get(kind)
        if spec is None:
            return False
        for k, v in spec.loot.items():
            self.resources[k] += v
        self.crates_found += 1
        self.effects.append(Effect(pos, pos, "loot"))
        self.message(f"{who} abriu {spec.name} em {pos}: {self.loot_text(kind)}.")
        if spec.noise > 0:
            self.emit_noise(pos, spec.noise, spec.name)
            self.message(f"O alarme da caixa fez barulho (raio {spec.noise})!")
        return True

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
            return False, (f"Fora do território (raio {BUILDING_STATS['hq'].build_radius} do CC / "
                           f"{BUILDING_STATS['tesla'].build_radius} de Tesla). Construa uma Tesla para expandir.")
        if self.ap < spec.ap:
            return False, f"AP insuficiente ({spec.ap} necessário)."
        missing = self._missing_resources(spec.cost)
        if missing:
            return False, f"Faltam recursos: {missing}."
        return True, ""

    @undoable
    def build(self, kind: str, pos: Pos) -> bool:
        ok, reason = self.can_build(kind, pos)
        if not ok:
            self.message(reason)
            return False
        spec = BUILD_SPECS[kind]
        self._spend(spec.ap, spec.cost)
        self.grid.place_building(BUILDING_TYPES[kind](pos))
        self.update_fog()
        self.emit_noise(pos, spec.noise, spec.name)
        self.message(f"{spec.name} construído(a) em {pos}.")
        self.collect_crate(pos, "A obra")
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

    @undoable
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
        """Passabilidade segundo o conhecimento do jogador (névoa esconde enxames/terreno)."""
        if not self.fog.is_known(pos):
            return True
        tile = self.grid.tile(pos)
        if not tile.terrain.passable or tile.building is not None or tile.unit is not None:
            return False
        return tile.swarm is None or not self.fog.is_visible(pos)

    def unit_moves(self, unit: Unit) -> dict[Pos, int]:
        if self.game_over or unit.moved or not unit.alive:
            return {}
        reach = self.grid.bfs_reachable(unit.pos, unit.move_range, self._unit_passable)
        # Torres de Vigia vazias são destino (não passagem)
        for p, steps in list(reach.items()):
            if steps >= unit.move_range:
                continue
            for n in self.grid.neighbors4(p):
                if self._can_enter_shelter(n) and reach.get(n, INF) > steps + 1:
                    reach[n] = steps + 1
        reach.pop(unit.pos, None)
        return reach

    def _path_to(self, start: Pos, dest: Pos, reach: dict[Pos, int]) -> list[Pos]:
        dist = dict(reach)
        dist[start] = 0
        path = [dest]
        cur = dest
        while dist[cur] > 1:
            cur = min(n for n in self.grid.neighbors4(cur) if dist.get(n) == dist[cur] - 1)
            path.append(cur)
        path.reverse()
        return path

    @undoable
    def move_unit(self, unit: Unit, dest: Pos) -> bool:
        reach = self.unit_moves(unit)
        if dest not in reach:
            self.message(f"{unit.name} não alcança {dest}.")
            return False
        unit.moved = True
        for step in self._path_to(unit.pos, dest, reach):
            if step == dest and self._can_enter_shelter(step):
                tower = self.grid.tile(step).building
                self.grid.remove_unit(unit)
                unit.pos = step
                self.grid.tile(step).unit = unit
                self.update_fog()
                self.message(f"{unit.name} entrou na {tower.name} (+{tower.range_bonus} alcance, "
                             f"+{tower.vision_bonus} visão).")
                break
            if not self.grid.is_free(step):
                tile = self.grid.tile(step)
                self._revealed = True
                if tile.swarm is not None:
                    self.message(f"Emboscada! {unit.name} topou com zumbis ocultos em {step}.")
                else:
                    self.message(f"{unit.name} encontrou terreno intransponível em {step}.")
                break
            self.grid.move_unit(unit, step)
            self.update_fog()
            self.collect_crate(step, unit.name)
        return True

    def attack_targets(self, unit: Unit) -> list[Pos]:
        if self.game_over or unit.acted or not unit.alive or self.ap < ATTACK_AP:
            return []
        targets = []
        for p in self.grid.tiles_in_radius(unit.pos, self.unit_range(unit), "chebyshev"):
            if not self.fog.is_visible(p):
                continue
            t = self.grid.tile(p)
            if t.swarm is not None or (t.building is not None and t.building.hostile):
                targets.append(p)
        return targets

    @undoable
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
            if killed:
                self.message(f"{unit.name} abateu {killed} {swarm.name}(s) em {pos}.")
            else:
                self.message(f"{unit.name} feriu um {swarm.name} em {pos}.")
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

    @undoable
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
        self.history.clear()
        self.ap = AP_PER_TURN
        for u in self.grid.units():
            u.reset_turn()
        self.update_fog()

    def propagate_noise(self) -> None:
        """Fase de som: transforma eventos pendentes em mapa de decibéis e alerta enxames."""
        self.history.clear()  # turno encerrado: nada mais pode ser desfeito
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
            hearing = swarm.spec.hearing
            best: Optional[tuple[int, NoiseEvent]] = None
            for ev in events:
                d = Grid.manhattan(swarm.pos, ev.pos)
                if d <= ev.radius + hearing:
                    level = ev.radius + hearing - d + 1
                    if best is None or level > best[0]:
                        best = (level, ev)
            if best is not None:
                swarm.alert(best[1].pos, NOISE_MEMORY_TURNS)
                alerted += 1
        if events:
            if self.fog.enabled:
                self.message(f"Barulho de {len(events)} fonte(s) ecoou pelo mapa...")
            else:
                self.message(f"Barulho de {len(events)} fonte(s) atraiu {alerted} enxame(s).")

    def _zombie_enter_cost(self, pos: Pos, flying: bool = False) -> Optional[float]:
        tile = self.grid.tile(pos)
        if not tile.terrain.passable:
            return None
        b = tile.building
        if b is not None:
            if b.hostile:
                return None
            if not b.civil:
                return 1.0 if flying else float(WALL_BASH_COST)
        return 1.0

    def _flying_enter_cost(self, pos: Pos) -> Optional[float]:
        return self._zombie_enter_cost(pos, flying=True)

    def civil_field(self, flying: bool = False) -> dict[Pos, float]:
        goals = [b.pos for b in self.grid.buildings() if b.civil and b.alive]
        goals += [u.pos for u in self.grid.units() if u.alive]
        cost = self._flying_enter_cost if flying else self._zombie_enter_cost
        return self.grid.dijkstra(goals, cost)

    def _field_for(self, swarm: ZombieSwarm, cache: dict[tuple, dict[Pos, float]]) -> dict[Pos, float]:
        target = swarm.noise_target
        if target is not None and Grid.manhattan(swarm.pos, target) <= 1:
            swarm.noise_target = None
            swarm.noise_turns = 0
            target = None
        key = (target, swarm.flying)
        if key not in cache:
            if target is None:
                cache[key] = self.civil_field(swarm.flying)
            else:
                cost = self._flying_enter_cost if swarm.flying else self._zombie_enter_cost
                cache[key] = self.grid.dijkstra([target], cost)
        return cache[key]

    def _swarm_targets(self, swarm: ZombieSwarm) -> list[Entity]:
        """Unidades/construções aliadas ao alcance de ataque do enxame."""
        if swarm.attack_range <= 1:
            cells = self.grid.neighbors4(swarm.pos)
        else:
            cells = [p for p in self.grid.tiles_in_radius(swarm.pos, swarm.attack_range, "manhattan")
                     if p != swarm.pos]
        targets: list[Entity] = []
        for p in cells:
            t = self.grid.tile(p)
            if t.building is not None and t.building.garrison and t.building.alive:
                targets.append(t.building)  # unidade abrigada fica protegida pela torre
            elif t.unit is not None and t.unit.alive:
                targets.append(t.unit)
            elif t.building is not None and not t.building.hostile and t.building.alive:
                targets.append(t.building)
        return targets

    def _leap_target(self, swarm: ZombieSwarm, over: Pos) -> Optional[Pos]:
        dest = (2 * over[0] - swarm.pos[0], 2 * over[1] - swarm.pos[1])
        if not self.grid.in_bounds(dest) or not self.grid.tile(dest).terrain.passable:
            return None
        return dest if self.grid.is_free(dest) else None

    def _step_swarm(self, swarm: ZombieSwarm, field: dict[Pos, float]) -> bool:
        """Move um passo seguindo o campo. Retorna True se ainda pode continuar andando."""
        if swarm.attack_range > 1 and swarm.noise_target is None:
            in_range = self._swarm_targets(swarm)
            if in_range:
                swarm.intent = min(in_range, key=self._attack_priority).pos
                return False
        current = field.get(swarm.pos, INF)
        candidates = sorted((field[n], n) for n in self.grid.neighbors4(swarm.pos)
                            if n in field and field[n] < current)
        for _, n in candidates:
            tile = self.grid.tile(n)
            b = tile.building
            if swarm.flying and b is not None and not b.hostile and not b.civil and tile.unit is None:
                dest = self._leap_target(swarm, n)
                if dest is not None:
                    self.grid.move_swarm(swarm, dest)
                    return True
            if tile.unit is not None or (b is not None and not b.hostile):
                swarm.intent = n
                return False
            if tile.swarm is not None:
                other = tile.swarm
                if not swarm.can_merge(other):
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
        cache: dict[tuple, dict[Pos, float]] = {}
        swarms = self.grid.swarms()
        for s in swarms:
            s.intent = None
            if not s.aggressive:
                key = (None, s.flying)
                if key not in cache:
                    cache[key] = self.civil_field(s.flying)
                if cache[key].get(s.pos, INF) <= AGGRO_DISTANCE:
                    s.aggressive = True
        swarms.sort(key=lambda s: (self._field_for(s, cache).get(s.pos, INF), s.pos))
        for s in swarms:
            if s.count <= 0 or self.grid.tile(s.pos).swarm is not s:
                continue
            if not s.aggressive:
                self._wander(s)
                continue
            for _ in range(s.speed):
                if not self._step_swarm(s, self._field_for(s, cache)):
                    break

    def ballistas_fire(self) -> None:
        self.update_fog()
        # qualquer construção com alcance e dano no CSV dispara (hoje: a Balista)
        ballistas = sorted((b for b in self.grid.buildings()
                            if b.alive and not b.hostile and b.attack_range > 0 and b.damage > 0),
                           key=lambda b: b.pos)
        for b in ballistas:
            in_range = [s for s in self.grid.swarms()
                        if Grid.chebyshev(b.pos, s.pos) <= b.attack_range
                        and self.fog.is_visible(s.pos)]
            if not in_range:
                continue
            target = min(in_range, key=lambda s: (Grid.chebyshev(b.pos, s.pos), -s.count, s.pos))
            killed = target.kill(b.damage)
            self.zombies_killed += killed
            self.effects.append(Effect(b.pos, target.pos, "bolt"))
            self.emit_noise(b.pos, b.stats.attack_noise, b.name)
            self.message(f"{b.name} em {b.pos} abateu {killed} {target.name}(s).")
            if not target.alive:
                self.grid.remove_swarm(target)
        self.garrisons_fire()

    def garrisons_fire(self) -> None:
        """Unidades abrigadas em Torres de Vigia que não agiram no turno disparam sozinhas."""
        for tower in sorted((b for b in self.grid.buildings() if b.garrison and b.alive),
                            key=lambda b: b.pos):
            unit = self.garrisoned(tower)
            if unit is None or unit.acted or not unit.alive:
                continue
            reach = self.unit_range(unit)
            in_range = [s for s in self.grid.swarms()
                        if Grid.chebyshev(tower.pos, s.pos) <= reach and self.fog.is_visible(s.pos)]
            if not in_range:
                continue
            target = min(in_range, key=lambda s: (Grid.chebyshev(tower.pos, s.pos), -s.count, s.pos))
            killed = target.kill(unit.damage)
            unit.acted = True
            self.zombies_killed += killed
            self.effects.append(Effect(tower.pos, target.pos, "shot"))
            self.emit_noise(tower.pos, unit.noise, unit.name)
            self.message(f"{unit.name} na {tower.name} abateu {killed} {target.name}(s).")
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
            targets = self._swarm_targets(s)
            if not targets:
                continue
            target = next((e for e in targets if e.pos == s.intent), None)
            if target is None:
                target = min(targets, key=self._attack_priority)
            dealt = target.take_damage(s.damage_against(isinstance(target, Building)))
            ranged = Grid.manhattan(s.pos, target.pos) > 1
            self.effects.append(Effect(s.pos, target.pos, "spit" if ranged else "bite"))
            if target.alive:
                verb = "cuspiu ácido" if ranged else "causou"
                self.message(f"{s.name} ({s.count}) {verb}: {dealt} de dano em {target.name}.")
            else:
                self._on_destroyed(target, s)

    def _on_destroyed(self, target: Entity, attacker: ZombieSwarm) -> None:
        if isinstance(target, Unit):
            self.grid.remove_unit(target)
            if attacker.space > 0 and Grid.manhattan(attacker.pos, target.pos) <= 1:
                attacker.count += 1
                self.message(f"{target.name} foi devorado e virou {attacker.name}!")
            else:
                self.message(f"{target.name} foi morto por {attacker.name}s!")
        elif isinstance(target, Tent):
            self.message(f"Tenda em {target.pos} caiu! A infecção se espalha...")
        elif isinstance(target, CommandCenter):
            self.message("O Centro de Comando foi destruído!")
            self.check_defeat()
        elif isinstance(target, Building):
            exposed = self.garrisoned(target)
            self.grid.remove_building(target)
            self.message(f"{target.name} em {target.pos} foi destruído(a).")
            if exposed is not None:
                self.message(f"{exposed.name} ficou exposto(a) nos escombros!")

    def resolve_infection(self) -> None:
        for b in self.grid.buildings():
            if isinstance(b, Tent) and not b.alive:
                self.grid.remove_building(b)
                self.grid.place_building(InfectedHouse(b.pos))
                self.message(f"Tenda em {b.pos} virou Casa Infectada!")
        for house in self.infected_houses():
            spawned = self._spawn_near(house.pos, house.stats.spawn)
            if spawned:
                self.message(f"Casa Infectada em {house.pos} gerou {spawned} zumbi(s).")

    def _spawn_near(self, pos: Pos, amount: int) -> int:
        remaining = amount
        for n in self.grid.neighbors4(pos):
            if remaining <= 0:
                break
            tile = self.grid.tile(n)
            if tile.swarm is not None and tile.swarm.kind == "walker" and tile.swarm.space > 0:
                add = min(tile.swarm.space, remaining)
                tile.swarm.count += add
                tile.swarm.aggressive = True
                remaining -= add
            elif self.grid.is_free(n):
                swarm = ZombieSwarm(n, remaining, aggressive=True)
                self.grid.place_swarm(swarm)
                remaining -= swarm.count
        return amount - remaining

    # ======================================================================
    # Ondas programadas
    # ======================================================================
    def _plan_waves(self, schedule: list[WaveRow]) -> list[PlannedWave]:
        """Resolve direções sorteadas ("?") e pontos de entrada já no início da partida,
        para que o jogador veja de onde cada onda virá."""
        rng = random.Random(self.seed * 1_000_003 + 7)  # não altera a sequência do mapa/IA
        by_turn: dict[int, list[WaveRow]] = {}
        for row in schedule:
            by_turn.setdefault(row.turn, []).append(row)
        plan: list[PlannedWave] = []
        last_sides: list[int] = []
        for turn in sorted(by_turn):
            rows = by_turn[turn]
            fixed = {direction_token(r.direction) for r in rows}
            sides: dict[object, int] = {t: t for t in fixed if isinstance(t, int)}
            for token in sorted(t for t in fixed if isinstance(t, str)):
                options = [d for d in range(4) if d not in sides.values()] or list(range(4))
                fresh = [d for d in options if d not in last_sides] or options  # varia a borda
                sides[token] = rng.choice(fresh)
            anchors: dict[int, Pos] = {}
            for side in sorted(set(sides.values())):
                length = GRID_W if side in (0, 1) else GRID_H
                lo, hi = WAVE_EDGE_SPREAD, max(WAVE_EDGE_SPREAD, length - 1 - WAVE_EDGE_SPREAD)
                anchors[side] = edge_pos(side, rng.randint(lo, hi))
            groups = []
            for r in rows:
                side = sides[direction_token(r.direction)]
                groups.append(WaveGroup(side, anchors[side], r.kind, r.swarms, r.size))
            plan.append(PlannedWave(turn, any(r.final for r in rows), groups))
            last_sides = sorted(set(sides.values()))
        return plan

    @property
    def next_wave(self) -> Optional[PlannedWave]:
        return next((w for w in self.waves if not w.spawned and w.turn >= self.turn), None)

    @property
    def final_wave(self) -> Optional[PlannedWave]:
        return next((w for w in self.waves if w.final), None)

    def _announce_next_wave(self) -> None:
        wave = self.next_wave
        if wave is None:
            return
        left = wave.turn - self.turn
        when = "ao fim deste turno" if left == 0 else f"em {left} turno(s)"
        label = "HORDA FINAL" if wave.final else "Próxima onda"
        self.message(f"{label}: ~{wave.zombies} zumbis pelo {wave.directions} {when}.")

    def _wave_spawn_cells(self, group: WaveGroup) -> list[Pos]:
        # evita bolsões isolados por terreno (ex.: mapas do editor)
        reachable = self.grid.dijkstra([self.hq.pos], self._zombie_enter_cost)
        side = group.side
        along0 = group.anchor[0] if side in (0, 1) else group.anchor[1]
        length = GRID_W if side in (0, 1) else GRID_H
        for spread in (WAVE_EDGE_SPREAD, length):  # se a entrada estiver bloqueada, usa a borda toda
            cells = []
            for depth in range(WAVE_EDGE_DEPTH):
                for along in range(max(0, along0 - spread), min(length, along0 + spread + 1)):
                    pos = edge_pos(side, along, depth)
                    if self.grid.is_free(pos):
                        cells.append((pos not in reachable, depth, abs(along - along0),
                                      self.rng.random(), pos))
            if cells:
                return [c[4] for c in sorted(cells)]
        return []

    def _spawn_group(self, group: WaveGroup) -> int:
        placed = 0
        for pos in self._wave_spawn_cells(group)[: group.swarms]:
            self.grid.place_swarm(ZombieSwarm(pos, group.size, aggressive=True, kind=group.kind))
            placed += 1
        return placed

    def _spawn_wave(self, wave: PlannedWave) -> dict[str, int]:
        spawned: dict[str, int] = {}
        for group in wave.groups:
            n = self._spawn_group(group)
            if n:
                spawned[group.kind] = spawned.get(group.kind, 0) + n
        wave.spawned = True
        return spawned

    @staticmethod
    def _describe_wave(spawned: dict[str, int]) -> str:
        return ", ".join(f"{n} {ZOMBIE_SPECS[k].name}" for k, n in spawned.items()) or "nenhum"

    def end_round(self) -> None:
        """Cleanup: produção, memória de som, ondas e condição de vitória."""
        prod = self.production()
        for k, v in prod.items():
            self.resources[k] += v
        self.message("Colônia produziu " + ", ".join(
            f"+{v} {RESOURCE_LABELS[k]}" for k, v in prod.items() if v or k == "gold") + ".")
        for s in self.grid.swarms():
            if s.noise_turns > 0:
                s.noise_turns -= 1
                if s.noise_turns == 0:
                    s.noise_target = None
        arrived = False
        for wave in self.waves:
            if wave.turn == self.turn and not wave.spawned:
                arrived = True
                spawned = self._spawn_wave(wave)
                if wave.final:
                    self.final_horde_spawned = True
                    self.message(f"A HORDA FINAL chegou pelo {wave.directions}: "
                                 f"{self._describe_wave(spawned)}!")
                else:
                    self.message(f"Onda pelo {wave.directions}: {self._describe_wave(spawned)}!")

        if self.check_defeat():
            return
        if self.turn >= MAX_TURNS:
            self._finish(True, f"Vitória! A colônia sobreviveu {MAX_TURNS} turnos.")
        elif self.final_horde_spawned and not self.grid.swarms() and not self.infected_houses():
            self._finish(True, "Vitória! A horda final foi repelida.")
        else:
            self.turn += 1
            nxt = self.next_wave
            if nxt is not None and (arrived or nxt.turn == self.turn):
                self._announce_next_wave()

    def check_defeat(self) -> bool:
        if not self.game_over and not self.hq.alive:
            self._finish(False, "Derrota! O Centro de Comando caiu.")
        return self.game_over and not self.victory

    def _finish(self, victory: bool, text: str) -> None:
        self.game_over = True
        self.victory = victory
        self.message(text)
