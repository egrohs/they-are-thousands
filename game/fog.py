"""Névoa de guerra (FOW) adaptada de They Are Billions.

* Inexplorado: preto; o jogador não sabe nada sobre o tile.
* Explorado: terreno e construções permanecem visíveis (memória), mas zumbis ficam ocultos.
* Visível: dentro do raio de visão de alguma unidade/construção aliada.

A exploração é sempre registrada, mesmo com a névoa desligada, para que ligá-la
no meio da partida mostre um estado coerente.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .grid import Grid, Pos
from .stats import VISION_RADIUS

if TYPE_CHECKING:
    from .entities import Building, Unit


def vision_tiles(grid: Grid, center: Pos, radius: int) -> list[Pos]:
    """Círculo discreto: dx² + dy² <= r² + r (bordas arredondadas)."""
    limit = radius * radius + radius
    return [p for p in grid.tiles_in_radius(center, radius, "chebyshev")
            if (p[0] - center[0]) ** 2 + (p[1] - center[1]) ** 2 <= limit]


class FogOfWar:
    def __init__(self, grid: Grid, enabled: bool = True):
        self.grid = grid
        self.enabled = enabled
        self.visible: set[Pos] = set()
        self.explored: set[Pos] = set()

    @staticmethod
    def vision_of(entity: "Building | Unit") -> int:
        return VISION_RADIUS.get(entity.kind, 0)

    def update(self) -> None:
        visible: set[Pos] = set()
        sources: list = [b for b in self.grid.buildings() if b.alive and not b.hostile]
        sources += [u for u in self.grid.units() if u.alive]
        for e in sources:
            r = self.vision_of(e)
            if r > 0:
                visible.update(vision_tiles(self.grid, e.pos, r))
        self.visible = visible
        self.explored |= visible

    def is_visible(self, pos: Pos) -> bool:
        return not self.enabled or pos in self.visible

    def is_explored(self, pos: Pos) -> bool:
        return not self.enabled or pos in self.explored
