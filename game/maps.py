"""Mapas personalizados: serialização JSON, validação e arquivos em `maps/`.

Formato (versão 1)::

    {
      "version": 1, "name": "Meu mapa", "width": 24, "height": 24,
      "terrain": ["GGFR...", ...],          # G=Campo F=Floresta R=Pedreira W=Água
      "resources": [[x, y, quantidade], ...],
      "buildings": [{"kind": "hq", "pos": [x, y]}, ...],
      "units": [{"kind": "soldier", "pos": [x, y]}, ...],
      "swarms": [{"kind": "walker", "count": 3, "pos": [x, y], "aggressive": false}, ...]
    }
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import GRID_H, GRID_W, MAPS_DIR, ZOMBIE_SPECS
from .entities import (BUILDING_TYPES, Building, CommandCenter, InfectedHouse, Ranger, Soldier,
                       Unit, ZombieSwarm)
from .grid import Grid, Pos, Terrain

MAP_VERSION = 1
TERRAIN_CHARS = {Terrain.GRASS: "G", Terrain.FOREST: "F", Terrain.ROCK: "R", Terrain.WATER: "W"}
CHAR_TERRAIN = {c: t for t, c in TERRAIN_CHARS.items()}
MAP_BUILDINGS: dict[str, type[Building]] = {"hq": CommandCenter, "infected": InfectedHouse,
                                            **BUILDING_TYPES}
MAP_UNITS: dict[str, type[Unit]] = {"soldier": Soldier, "ranger": Ranger}
MAX_RESOURCE = 99


class MapError(ValueError):
    """Arquivo de mapa inválido."""


# ----------------------------------------------------------------------------
def grid_to_data(grid: Grid, name: str) -> dict[str, Any]:
    terrain = ["".join(TERRAIN_CHARS[grid.tile((x, y)).terrain] for x in range(grid.width))
               for y in range(grid.height)]
    tiles = list(grid)
    return {
        "version": MAP_VERSION,
        "name": name,
        "width": grid.width,
        "height": grid.height,
        "terrain": terrain,
        "resources": [[t.x, t.y, t.resource_amount] for t in tiles
                      if t.terrain.resource and t.resource_amount > 0],
        "buildings": [{"kind": t.building.kind, "pos": [t.x, t.y]}
                      for t in tiles if t.building is not None],
        "units": [{"kind": t.unit.kind, "pos": [t.x, t.y]} for t in tiles if t.unit is not None],
        "swarms": [{"kind": t.swarm.kind, "count": t.swarm.count, "pos": [t.x, t.y],
                    "aggressive": t.swarm.aggressive} for t in tiles if t.swarm is not None],
    }


def _pos(entry: dict, where: str) -> Pos:
    p = entry.get("pos") if isinstance(entry, dict) else None
    if (not isinstance(p, (list, tuple)) or len(p) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in p)):
        raise MapError(f"{where}: posição inválida ({p!r}).")
    if not (0 <= p[0] < GRID_W and 0 <= p[1] < GRID_H):
        raise MapError(f"{where}: posição {tuple(p)} fora do mapa.")
    return (p[0], p[1])


def build_grid(data: Any) -> tuple[Grid, CommandCenter]:
    """Valida `data` e monta a grade. Lança MapError com mensagem legível."""
    if not isinstance(data, dict):
        raise MapError("O mapa deve ser um objeto JSON.")
    if data.get("version") != MAP_VERSION:
        raise MapError(f"Versão de mapa não suportada: {data.get('version')!r}.")
    if data.get("width") != GRID_W or data.get("height") != GRID_H:
        raise MapError(f"O mapa precisa ter {GRID_W}x{GRID_H} tiles.")
    rows = data.get("terrain")
    if not isinstance(rows, list) or len(rows) != GRID_H:
        raise MapError(f"'terrain' precisa de {GRID_H} linhas.")
    grid = Grid(GRID_W, GRID_H)
    for y, row in enumerate(rows):
        if not isinstance(row, str) or len(row) != GRID_W:
            raise MapError(f"Linha {y} do terreno precisa de {GRID_W} caracteres.")
        for x, ch in enumerate(row):
            if ch not in CHAR_TERRAIN:
                raise MapError(f"Terreno desconhecido '{ch}' em ({x}, {y}).")
            grid.tile((x, y)).terrain = CHAR_TERRAIN[ch]

    for entry in data.get("resources", []):
        if (not isinstance(entry, (list, tuple)) or len(entry) != 3
                or not all(isinstance(v, int) for v in entry)):
            raise MapError(f"Recurso inválido: {entry!r}.")
        x, y, amount = entry
        if not grid.in_bounds((x, y)):
            raise MapError(f"Recurso fora do mapa: {(x, y)}.")
        tile = grid.tile((x, y))
        if tile.terrain.resource:
            tile.resource_amount = max(0, min(MAX_RESOURCE, amount))

    hq: list[CommandCenter] = []
    for i, entry in enumerate(data.get("buildings", [])):
        where = f"Construção #{i + 1}"
        kind = entry.get("kind") if isinstance(entry, dict) else None
        if kind not in MAP_BUILDINGS:
            raise MapError(f"{where}: tipo desconhecido {kind!r}.")
        pos = _pos(entry, where)
        tile = grid.tile(pos)
        if not tile.terrain.buildable:
            raise MapError(f"{where}: {tile.terrain.label} em {pos} não aceita construções.")
        if tile.occupied:
            raise MapError(f"{where}: tile {pos} já ocupado.")
        building = MAP_BUILDINGS[kind](pos)
        grid.place_building(building)
        if isinstance(building, CommandCenter):
            hq.append(building)
    if len(hq) != 1:
        raise MapError(f"O mapa precisa de exatamente 1 Centro de Comando (tem {len(hq)}).")

    for i, entry in enumerate(data.get("units", [])):
        where = f"Unidade #{i + 1}"
        kind = entry.get("kind") if isinstance(entry, dict) else None
        if kind not in MAP_UNITS:
            raise MapError(f"{where}: tipo desconhecido {kind!r}.")
        pos = _pos(entry, where)
        if grid.tile(pos).occupied or not grid.tile(pos).terrain.passable:
            raise MapError(f"{where}: tile {pos} indisponível.")
        grid.place_unit(MAP_UNITS[kind](pos))

    for i, entry in enumerate(data.get("swarms", [])):
        where = f"Enxame #{i + 1}"
        kind = entry.get("kind") if isinstance(entry, dict) else None
        if kind not in ZOMBIE_SPECS:
            raise MapError(f"{where}: tipo de zumbi desconhecido {kind!r}.")
        count = entry.get("count")
        if not isinstance(count, int) or count < 1:
            raise MapError(f"{where}: quantidade inválida ({count!r}).")
        pos = _pos(entry, where)
        if grid.tile(pos).occupied or not grid.tile(pos).terrain.passable:
            raise MapError(f"{where}: tile {pos} indisponível.")
        grid.place_swarm(ZombieSwarm(pos, count, bool(entry.get("aggressive", False)), kind))
    return grid, hq[0]


# ----------------------------------------------------------------------------
def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "_", name.strip().lower()).strip("_")
    return slug or "mapa"


def map_path(name: str, folder: Path = MAPS_DIR) -> Path:
    return Path(folder) / f"{slugify(name)}.json"


def save_map(data: dict[str, Any], folder: Path = MAPS_DIR) -> Path:
    build_grid(data)
    path = map_path(data.get("name", "mapa"), folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_map(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MapError(f"Não foi possível ler {Path(path).name}: {exc}") from exc
    build_grid(data)
    data.setdefault("name", Path(path).stem)
    return data


def list_maps(folder: Path = MAPS_DIR) -> list[Path]:
    folder = Path(folder)
    return sorted(folder.glob("*.json")) if folder.is_dir() else []
