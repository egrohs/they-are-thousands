"""Stats de construções, unidades e zumbis lidos de CSVs em `data/` (balanceamento).

* `data/buildings.csv`, `data/units.csv`, `data/zombies.csv` – uma linha por tipo, `id` como chave.
* Aceita separador `,` ou `;` e, com `;`, vírgula decimal (formato do Excel em pt-BR).
* Colunas `notes`/`description` são livres; colunas desconhecidas geram erro (evita typos).
* Erros viram `StatsError` com arquivo, linha e coluna.
"""
from __future__ import annotations

import csv
import dataclasses
import io
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, TypeVar

from .config import DATA_DIR, FINAL_HORDE, START_SWARM_TYPES, WAVES

Color = tuple[int, int, int]


class StatsError(ValueError):
    """CSV de stats inválido."""


@dataclass(frozen=True)
class BuildingStats:
    id: str
    name: str
    symbol: str
    hp: int
    buildable: bool = False   # aparece nos botões de construção
    ap: int = 0
    gold: int = 0
    wood: int = 0
    stone: int = 0
    noise: int = 0            # ruído ao construir
    gold_income: int = 0      # ouro por fim de turno
    vision: int = 0           # raio de visão (névoa)
    build_radius: int = 0     # >0: expande o território
    attack_range: int = 0     # >0: dispara automaticamente (Chebyshev)
    damage: int = 0
    attack_noise: int = 0
    spawn: int = 0            # zumbis gerados por turno (Casa Infectada)
    notes: str = ""

    @property
    def cost(self) -> dict[str, int]:
        return {"gold": self.gold, "wood": self.wood, "stone": self.stone}


@dataclass(frozen=True)
class UnitStats:
    id: str
    name: str
    symbol: str
    hp: int
    move: int
    attack_range: int
    damage: int
    noise: int
    vision: int
    notes: str = ""


@dataclass(frozen=True)
class ZombieSpec:
    id: str
    name: str
    symbol: str
    hp: int                    # HP de cada zumbi da pilha
    speed: int                 # passos por turno quando agressivo
    attack: float              # dano por zumbi (dano do enxame = ceil(qtd * attack))
    max_stack: int             # zumbis por tile
    attack_range: int = 1      # >1: ataque à distância (Manhattan)
    structure_mult: float = 1.0
    flying: bool = False       # salta muros/balistas/teslas
    hearing: int = 0           # bônus no raio de barulho que o alerta
    color: Color = (105, 36, 36)
    description: str = ""


FREE_TEXT = {"notes", "description", "name", "symbol"}
MIN_VALUES = {"hp": 1, "max_stack": 1, "attack_range": 0, "attack": 0, "structure_mult": 0}
REQUIRED_BUILDINGS = {"hq", "tent", "wall", "ballista", "tesla", "infected"}
REQUIRED_UNITS = {"soldier", "ranger"}
REQUIRED_ZOMBIES = {"walker"}  # gerado por Casas Infectadas
TRUE = {"1", "true", "sim", "s", "yes", "y", "x"}
FALSE = {"0", "false", "nao", "não", "n", "no", ""}

T = TypeVar("T")


def _parse_color(text: str) -> Color:
    t = text.strip().lstrip("#")
    if len(t) == 6:
        try:
            return (int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))
        except ValueError:
            pass
    parts = [p.strip() for p in text.replace(";", " ").replace(",", " ").split()]
    if len(parts) == 3 and all(p.isdigit() and int(p) <= 255 for p in parts):
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    raise ValueError("use #rrggbb")


def _convert(raw: str, typ: Any, decimal_comma: bool) -> Any:
    text = raw.strip()
    if typ in ("str", str):
        return text
    if typ in ("bool", bool):
        low = text.lower()
        if low in TRUE:
            return True
        if low in FALSE:
            return False
        raise ValueError("use 0/1")
    if typ in ("int", int):
        try:
            number = float(text.replace(",", ".") if decimal_comma else text)
        except ValueError:
            raise ValueError("número inteiro esperado") from None
        if not number.is_integer():
            raise ValueError("número inteiro esperado")
        return int(number)
    if typ in ("float", float):
        try:
            return float(text.replace(",", ".") if decimal_comma else text)
        except ValueError:
            raise ValueError("número esperado; use ponto decimal (ou ';' + vírgula)") from None
    if typ == "Color":
        return _parse_color(text)
    raise TypeError(f"Tipo não suportado: {typ}")


def read_table(path: Path, cls: type[T]) -> dict[str, T]:
    """Lê `path` e converte cada linha em `cls` (dataclass), indexando por `id`."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise StatsError(f"Não foi possível ler {path}: {exc}") from exc
    header_line = text.splitlines()[0] if text.strip() else ""
    delimiter = ";" if header_line.count(";") > header_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    columns = [c.strip() for c in (reader.fieldnames or [])]
    reader.fieldnames = columns
    specs = {f.name: f for f in fields(cls)}  # type: ignore[arg-type]
    required = {n for n, f in specs.items()
                if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING}
    where = path.name
    unknown = [c for c in columns if c and c not in specs]
    if unknown:
        raise StatsError(f"{where}: coluna(s) desconhecida(s): {', '.join(unknown)}. "
                         f"Válidas: {', '.join(specs)}.")
    missing = required - set(columns)
    if missing:
        raise StatsError(f"{where}: faltam as colunas obrigatórias: {', '.join(sorted(missing))}.")

    table: dict[str, T] = {}
    for row in reader:
        line = reader.line_num
        if (not any(isinstance(v, str) and v.strip() for v in row.values())
                or (row.get("id") or "").strip().startswith("#")):
            continue
        values: dict[str, Any] = {}
        for name, raw in row.items():
            if name is None:
                raise StatsError(f"{where} linha {line}: valores a mais que colunas.")
            if raw is None:
                raise StatsError(f"{where} linha {line}: faltam valores (coluna '{name}').")
            if not name:
                continue
            field = specs[name]
            if raw.strip() == "" and name not in FREE_TEXT:
                if name in required:
                    raise StatsError(f"{where} linha {line}: coluna '{name}' vazia.")
                continue
            try:
                value = _convert(raw, field.type, delimiter == ";")
            except ValueError as exc:
                raise StatsError(f"{where} linha {line}, coluna '{name}': valor inválido "
                                 f"{raw!r} ({exc}).") from None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if value < MIN_VALUES.get(name, 0):
                    raise StatsError(f"{where} linha {line}, coluna '{name}': deve ser "
                                     f">= {MIN_VALUES.get(name, 0)} (recebido {value}).")
            values[name] = value
        key = values["id"]
        if not key:
            raise StatsError(f"{where} linha {line}: 'id' vazio.")
        if key in table:
            raise StatsError(f"{where} linha {line}: id duplicado '{key}'.")
        table[key] = cls(**values)
    return table


@dataclass(frozen=True)
class GameStats:
    buildings: dict[str, BuildingStats]
    units: dict[str, UnitStats]
    zombies: dict[str, ZombieSpec]


def _check_ids(where: str, table: dict, required: set[str], exact: bool) -> None:
    missing = required - set(table)
    if missing:
        raise StatsError(f"{where}: faltam os ids obrigatórios: {', '.join(sorted(missing))}.")
    extra = set(table) - required
    if exact and extra:
        raise StatsError(f"{where}: ids sem comportamento implementado: {', '.join(sorted(extra))} "
                         f"(permitidos: {', '.join(sorted(required))}).")


def load_stats(folder: Path = DATA_DIR) -> GameStats:
    folder = Path(folder)
    buildings = read_table(folder / "buildings.csv", BuildingStats)
    units = read_table(folder / "units.csv", UnitStats)
    zombies = read_table(folder / "zombies.csv", ZombieSpec)
    _check_ids("buildings.csv", buildings, REQUIRED_BUILDINGS, exact=True)
    _check_ids("units.csv", units, REQUIRED_UNITS, exact=True)
    _check_ids("zombies.csv", zombies, REQUIRED_ZOMBIES, exact=False)
    referenced = {k for groups in WAVES.values() for k, _, _ in groups}
    referenced |= {k for k, _, _ in FINAL_HORDE} | {k for k, _ in START_SWARM_TYPES}
    unknown = referenced - set(zombies)
    if unknown:
        raise StatsError(f"zombies.csv: tipos usados nas ondas (config.py) não definidos: "
                         f"{', '.join(sorted(unknown))}.")
    for kind in ("hq", "infected"):
        if buildings[kind].buildable:
            raise StatsError(f"buildings.csv: '{kind}' não pode ter buildable=1.")
    return GameStats(buildings, units, zombies)


STATS = load_stats()
BUILDING_STATS: dict[str, BuildingStats] = STATS.buildings
UNIT_SPECS: dict[str, UnitStats] = STATS.units
ZOMBIE_SPECS: dict[str, ZombieSpec] = STATS.zombies
# construções que o jogador pode erguer (botões/atalhos)
BUILD_SPECS: dict[str, BuildingStats] = {k: v for k, v in BUILDING_STATS.items() if v.buildable}
VISION_RADIUS: dict[str, int] = {**{k: v.vision for k, v in BUILDING_STATS.items()},
                                 **{k: v.vision for k, v in UNIT_SPECS.items()}}
