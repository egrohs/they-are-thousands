"""Névoa de guerra (FOW) adaptada de They Are Billions.

Quatro camadas:

* Inexplorado: preto; o jogador não sabe nada sobre o tile.
* Escuridão: já explorado, mas sem nenhuma unidade/construção aliada por perto
  (além de visão + `FOG_MEMORY_MARGIN`): oculta tudo — terreno, construções, caixas e zumbis.
* Memória: explorado e perto de aliados; terreno, construções e caixas aparecem
  esmaecidos, mas zumbis ficam ocultos.
* Visível: dentro do raio de visão de alguma unidade/construção aliada.

A exploração é sempre registrada, mesmo com a névoa desligada, para que ligá-la
no meio da partida mostre um estado coerente.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .config import FOG_MEMORY_MARGIN
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
        self.explored: set[Pos] = set()   # histórico: já foi visto alguma vez
        self.nearby: set[Pos] = set()     # alcance de memória (visão + margem) dos aliados
        self.margin = FOG_MEMORY_MARGIN

    @staticmethod
    def vision_of(entity: "Building | Unit") -> int:
        return VISION_RADIUS.get(entity.kind, 0)

    def update(self) -> None:
        visible: set[Pos] = set()
        nearby: set[Pos] = set()
        sources: list = [b for b in self.grid.buildings() if b.alive and not b.hostile]
        sources += [u for u in self.grid.units() if u.alive]
        for e in sources:
            r = self.vision_of(e)
            shelter = self.grid.tile(e.pos).building
            if shelter is not None and shelter is not e and shelter.garrison:
                r = max(r, VISION_RADIUS.get(shelter.kind, 0)) + shelter.vision_bonus
            if r > 0:
                visible.update(vision_tiles(self.grid, e.pos, r))
            nearby.update(vision_tiles(self.grid, e.pos, r + self.margin))
        self.visible = visible
        self.nearby = nearby
        self.explored |= visible

    def is_visible(self, pos: Pos) -> bool:
        return not self.enabled or pos in self.visible

    def is_explored(self, pos: Pos) -> bool:
        """Já foi visto alguma vez (histórico, inclui tiles hoje na escuridão)."""
        return not self.enabled or pos in self.explored

    def is_known(self, pos: Pos) -> bool:
        """O jogador enxerga o tile agora: visível ou na memória (explorado e perto de aliados)."""
        return not self.enabled or pos in self.visible or (pos in self.explored and pos in self.nearby)

    def is_dark(self, pos: Pos) -> bool:
        """Explorado, mas longe de qualquer aliado: tudo oculto."""
        return self.enabled and pos in self.explored and not self.is_known(pos)
