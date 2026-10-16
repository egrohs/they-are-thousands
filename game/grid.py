"""Modelo lógico da grade: terreno, ocupação, distâncias e pathfinding."""
from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable, Iterable, Iterator, Optional

if TYPE_CHECKING:
    from .entities import Building, Unit, ZombieSwarm

Pos = tuple[int, int]
INF = float("inf")


class Terrain(Enum):
    GRASS = "grass"
    FOREST = "forest"
    ROCK = "rock"
    WATER = "water"

    @property
    def passable(self) -> bool:
        """Só Campo é atravessável: Floresta, Pedreira e Água bloqueiam unidades e zumbis."""
        return self is Terrain.GRASS

    @property
    def buildable(self) -> bool:
        return self is Terrain.GRASS

    @property
    def resource(self) -> Optional[str]:
        if self is Terrain.FOREST:
            return "wood"
        if self is Terrain.ROCK:
            return "stone"
        return None

    @property
    def label(self) -> str:
        return {
            Terrain.GRASS: "Campo",
            Terrain.FOREST: "Floresta",
            Terrain.ROCK: "Pedreira",
            Terrain.WATER: "Água",
        }[self]


@dataclass(eq=False)
class Tile:
    x: int
    y: int
    terrain: Terrain = Terrain.GRASS
    resource_amount: int = 0
    building: Optional["Building"] = None
    unit: Optional["Unit"] = None
    swarm: Optional["ZombieSwarm"] = None

    @property
    def pos(self) -> Pos:
        return (self.x, self.y)

    @property
    def occupied(self) -> bool:
        return self.building is not None or self.unit is not None or self.swarm is not None


class Grid:
    DIRS4: tuple[Pos, ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))
    DIRS8: tuple[Pos, ...] = DIRS4 + ((1, 1), (1, -1), (-1, 1), (-1, -1))

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._tiles = [[Tile(x, y) for x in range(width)] for y in range(height)]

    # --- acesso -----------------------------------------------------------
    def in_bounds(self, pos: Pos) -> bool:
        x, y = pos
        return 0 <= x < self.width and 0 <= y < self.height

    def tile(self, pos: Pos) -> Tile:
        x, y = pos
        if not self.in_bounds(pos):
            raise IndexError(f"Posição fora da grade: {pos}")
        return self._tiles[y][x]

    def __iter__(self) -> Iterator[Tile]:
        for row in self._tiles:
            yield from row

    def _offsets(self, pos: Pos, dirs: Iterable[Pos]) -> list[Pos]:
        x, y = pos
        return [p for p in ((x + dx, y + dy) for dx, dy in dirs) if self.in_bounds(p)]

    def neighbors4(self, pos: Pos) -> list[Pos]:
        return self._offsets(pos, self.DIRS4)

    def neighbors8(self, pos: Pos) -> list[Pos]:
        return self._offsets(pos, self.DIRS8)

    # --- distâncias -------------------------------------------------------
    @staticmethod
    def manhattan(a: Pos, b: Pos) -> int:
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    @staticmethod
    def chebyshev(a: Pos, b: Pos) -> int:
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

    def distance(self, a: Pos, b: Pos, metric: str = "chebyshev") -> int:
        if metric == "manhattan":
            return self.manhattan(a, b)
        if metric == "chebyshev":
            return self.chebyshev(a, b)
        raise ValueError(f"Métrica desconhecida: {metric}")

    def tiles_in_radius(self, center: Pos, radius: int, metric: str = "chebyshev") -> list[Pos]:
        cx, cy = center
        result = []
        for y in range(max(0, cy - radius), min(self.height, cy + radius + 1)):
            for x in range(max(0, cx - radius), min(self.width, cx + radius + 1)):
                if self.distance(center, (x, y), metric) <= radius:
                    result.append((x, y))
        return result

    # --- ocupação ---------------------------------------------------------
    def is_free(self, pos: Pos) -> bool:
        if not self.in_bounds(pos):
            return False
        t = self.tile(pos)
        return t.terrain.passable and not t.occupied

    def place_building(self, building: "Building") -> None:
        t = self.tile(building.pos)
        if t.occupied:
            raise ValueError(f"Tile {building.pos} já ocupado")
        t.building = building

    def remove_building(self, building: "Building") -> None:
        t = self.tile(building.pos)
        if t.building is building:
            t.building = None

    def place_unit(self, unit: "Unit") -> None:
        t = self.tile(unit.pos)
        if t.occupied or not t.terrain.passable:
            raise ValueError(f"Tile {unit.pos} indisponível para unidade")
        t.unit = unit

    def remove_unit(self, unit: "Unit") -> None:
        t = self.tile(unit.pos)
        if t.unit is unit:
            t.unit = None

    def move_unit(self, unit: "Unit", dest: Pos) -> None:
        if not self.is_free(dest):
            raise ValueError(f"Destino {dest} indisponível")
        self.remove_unit(unit)
        unit.pos = dest
        self.tile(dest).unit = unit

    def place_swarm(self, swarm: "ZombieSwarm") -> None:
        t = self.tile(swarm.pos)
        if t.occupied or not t.terrain.passable:
            raise ValueError(f"Tile {swarm.pos} indisponível para enxame")
        t.swarm = swarm

    def remove_swarm(self, swarm: "ZombieSwarm") -> None:
        t = self.tile(swarm.pos)
        if t.swarm is swarm:
            t.swarm = None

    def move_swarm(self, swarm: "ZombieSwarm", dest: Pos) -> None:
        if not self.is_free(dest):
            raise ValueError(f"Destino {dest} indisponível")
        self.remove_swarm(swarm)
        swarm.pos = dest
        self.tile(dest).swarm = swarm

    def buildings(self) -> list["Building"]:
        return [t.building for t in self if t.building is not None]

    def units(self) -> list["Unit"]:
        return [t.unit for t in self if t.unit is not None]

    def swarms(self) -> list["ZombieSwarm"]:
        return [t.swarm for t in self if t.swarm is not None]

    # --- pathfinding ------------------------------------------------------
    def bfs_reachable(self, start: Pos, max_steps: int,
                      passable: Callable[[Pos], bool]) -> dict[Pos, int]:
        """BFS 4-direções: retorna {pos: passos} alcançáveis (inclui start com 0)."""
        dist = {start: 0}
        queue = deque([start])
        while queue:
            cur = queue.popleft()
            if dist[cur] >= max_steps:
                continue
            for n in self.neighbors4(cur):
                if n not in dist and passable(n):
                    dist[n] = dist[cur] + 1
                    queue.append(n)
        return dist

    def dijkstra(self, goals: Iterable[Pos],
                 enter_cost: Callable[[Pos], Optional[float]]) -> dict[Pos, float]:
        """Campo de fluxo multi-fonte. dist[p] = custo de p até o objetivo mais próximo.

        enter_cost(p) devolve o custo para entrar em p, ou None se intransponível.
        """
        goal_set = set(goals)
        dist: dict[Pos, float] = {g: 0.0 for g in goal_set}
        heap = [(0.0, g) for g in goal_set]
        heapq.heapify(heap)
        while heap:
            d, cur = heapq.heappop(heap)
            if d > dist.get(cur, INF):
                continue
            step = 1.0 if cur in goal_set else enter_cost(cur)
            if step is None:
                continue
            for n in self.neighbors4(cur):
                if n not in goal_set and enter_cost(n) is None:
                    continue
                nd = d + step
                if nd < dist.get(n, INF):
                    dist[n] = nd
                    heapq.heappush(heap, (nd, n))
        return dist
