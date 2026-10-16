"""Stats de construções, unidades e zumbis lidos de CSVs em `data/` (balanceamento).

* `data/buildings.csv`, `data/units.csv`, `data/zombies.csv` – uma linha por tipo, `id` como chave.
* `data/waves.csv` – cronograma de ondas (turno, direção, tipo, enxames, tamanho).
* `data/crates.csv` – caixas de recursos espalhadas pelo mapa (conteúdo e raridade).
* `data/heroes.csv` / `data/skills.csv` – heróis (um por papel) e suas habilidades.
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

from .config import DATA_DIR, MAX_TURNS, START_SWARM_TYPES

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
    garrison: bool = False    # abriga 1 unidade (Torre de Vigia)
    range_bonus: int = 0      # bônus de alcance da unidade abrigada
    vision_bonus: int = 0     # bônus de visão da unidade abrigada
    harvest: str = ""         # recurso extraído do terreno ao redor: wood (Floresta) / stone (Pedreira)
    harvest_radius: int = 0   # raio (Chebyshev) dos tiles explorados
    harvest_tiles: int = 0    # tiles necessários por 1 unidade de recurso/turno
    harvest_max: int = 0      # produção máxima por turno
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


@dataclass(frozen=True)
class WaveRow:
    """Grupo de uma onda programada (`data/waves.csv`); várias linhas podem ter o mesmo turno."""
    turn: int                  # a onda chega ao fim deste turno
    direction: str             # N, S, L, O; "?" (ou ?1, ?2...) = borda sorteada na partida
    kind: str
    swarms: int
    size: int
    final: bool = False        # pertence à horda final
    notes: str = ""


@dataclass(frozen=True)
class CrateStats:
    """Tipo de caixa de recursos (`data/crates.csv`), aberta por uma unidade que pisa nela."""
    id: str
    name: str
    symbol: str
    weight: int = 1            # peso no sorteio dos mapas aleatórios (0 = só no editor)
    gold: int = 0
    wood: int = 0
    stone: int = 0
    noise: int = 0             # ruído ao abrir (atrai zumbis)
    min_dist: int = 6          # distância mínima (Chebyshev) do centro do mapa
    color: Color = (200, 160, 80)
    notes: str = ""

    @property
    def loot(self) -> dict[str, int]:
        return {k: v for k, v in (("gold", self.gold), ("wood", self.wood),
                                  ("stone", self.stone)) if v > 0}


@dataclass(frozen=True)
class HeroStats:
    """Herói (`data/heroes.csv`); `id` é o papel e define as habilidades (skills.csv)."""
    id: str
    name: str
    role: str
    symbol: str
    hp: int
    move: int
    attack_range: int
    damage: int
    armor: int = 0              # reduz cada golpe recebido (mínimo 1 de dano)
    noise: int = 0
    vision: int = 4
    mana: int = 0
    mana_regen: int = 0
    hp_per_level: int = 0
    damage_per_level: int = 0
    mana_per_level: int = 0
    color: Color = (200, 200, 220)
    notes: str = ""


@dataclass(frozen=True)
class SkillStats:
    """Habilidade de herói (`data/skills.csv`); `id` define o efeito implementado."""
    id: str
    hero: str
    name: str
    ap: int = 1
    cooldown: int = 0          # turnos de recarga após o uso
    mana: int = 0
    range: int = 0             # alcance do alvo (Chebyshev; 'line' usa linha/coluna)
    radius: int = 0            # raio da área (Chebyshev)
    power: int = 0             # dano / cura / armadura / empurrão / raio de ruído
    per_level: int = 0         # power extra por nível acima do 1
    duration: int = 0          # turnos de efeito
    noise: int = 0             # ruído emitido pelo herói ao usar
    target: str = "self"       # self, enemy, ally, tile, line, move
    notes: str = ""


# lado da grade: 0 = norte (y=0), 1 = sul, 2 = oeste (x=0), 3 = leste
DIRECTIONS = {"N": 0, "S": 1, "O": 2, "W": 2, "L": 3, "E": 3}
DIRECTION_NAMES = {0: "Norte", 1: "Sul", 2: "Oeste", 3: "Leste"}


def direction_token(text: str) -> "int | str | None":
    """Converte a coluna `direction`: lado fixo (int) ou marcador de sorteio ("?1", "?2"...)."""
    t = text.strip().upper()
    if t in DIRECTIONS:
        return DIRECTIONS[t]
    if t.startswith("?") and (t[1:] == "" or t[1:].isdigit()):
        return "?" + (t[1:] or "1")
    return None


FREE_TEXT = {"notes", "description", "name", "symbol"}
MIN_VALUES = {"swarms": 1, "size": 1, "hp": 1, "max_stack": 1, "attack_range": 0, "attack": 0, "structure_mult": 0}
REQUIRED_BUILDINGS = {"hq", "tent", "wall", "ballista", "tesla", "watchtower", "sawmill", "quarry",
                      "infected"}
HARVEST_KINDS = {"wood", "stone"}
REQUIRED_UNITS = {"soldier", "ranger"}
REQUIRED_HEROES = {"tank", "ranged", "rogue", "healer", "mage"}
SKILL_EFFECTS = {"taunt": "tank", "guard": "tank", "pierce": "ranged", "snipe": "ranged",
                 "stealth": "rogue", "shove": "rogue", "lure": "rogue", "heal": "healer",
                 "heal_aoe": "healer", "fireball": "mage", "root": "mage", "blink": "mage"}
SKILL_TARGETS = {"self", "enemy", "ally", "tile", "line", "move"}
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


def read_rows(path: Path, cls: type[T]) -> list[tuple[int, T]]:
    """Lê `path` e converte cada linha em `cls` (dataclass); retorna (nº da linha, objeto)."""
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

    rows: list[tuple[int, T]] = []
    for row in reader:
        line = reader.line_num
        if (not any(isinstance(v, str) and v.strip() for v in row.values())
                or (next(iter(row.values()), "") or "").strip().startswith("#")):
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
        rows.append((line, cls(**values)))
    return rows


def read_table(path: Path, cls: type[T]) -> dict[str, T]:
    """Como `read_rows`, mas indexa pelo campo `id` (único e obrigatório)."""
    table: dict[str, T] = {}
    for line, obj in read_rows(path, cls):
        key = getattr(obj, "id")
        if not key:
            raise StatsError(f"{Path(path).name} linha {line}: 'id' vazio.")
        if key in table:
            raise StatsError(f"{Path(path).name} linha {line}: id duplicado '{key}'.")
        table[key] = obj
    return table


def _check_waves(rows: list[tuple[int, WaveRow]], zombies: dict[str, ZombieSpec]) -> list[WaveRow]:
    final_turns = set()
    for line, w in rows:
        where = f"waves.csv linha {line}"
        if not 1 <= w.turn <= MAX_TURNS:
            raise StatsError(f"{where}, coluna 'turn': deve estar entre 1 e {MAX_TURNS}.")
        if w.kind not in zombies:
            raise StatsError(f"{where}, coluna 'kind': tipo '{w.kind}' não existe em zombies.csv.")
        if direction_token(w.direction) is None:
            raise StatsError(f"{where}, coluna 'direction': use N, S, L, O, ? ou ?1, ?2...")
        if w.final:
            final_turns.add(w.turn)
    if len(final_turns) > 1:
        raise StatsError(f"waves.csv: a horda final (final=1) deve ter um único turno; "
                         f"encontrados {sorted(final_turns)}.")
    return sorted((w for _, w in rows), key=lambda w: w.turn)


@dataclass(frozen=True)
class GameStats:
    buildings: dict[str, BuildingStats]
    units: dict[str, UnitStats]
    zombies: dict[str, ZombieSpec]
    waves: list[WaveRow]
    crates: dict[str, CrateStats] = dataclasses.field(default_factory=dict)
    heroes: dict[str, HeroStats] = dataclasses.field(default_factory=dict)
    skills: dict[str, SkillStats] = dataclasses.field(default_factory=dict)


def _check_skills(skills: dict[str, SkillStats]) -> dict[str, SkillStats]:
    for s in skills.values():
        if s.hero != SKILL_EFFECTS[s.id]:
            raise StatsError(f"skills.csv: '{s.id}' pertence ao herói '{SKILL_EFFECTS[s.id]}' "
                             f"(recebido '{s.hero}').")
        if s.target not in SKILL_TARGETS:
            raise StatsError(f"skills.csv: '{s.id}' tem target inválido '{s.target}' "
                             f"(use {', '.join(sorted(SKILL_TARGETS))}).")
        if s.target != "self" and s.range < 1:
            raise StatsError(f"skills.csv: '{s.id}' precisa de range >= 1.")
    return skills


def _check_crates(crates: dict[str, CrateStats]) -> dict[str, CrateStats]:
    for c in crates.values():
        if not c.loot:
            raise StatsError(f"crates.csv: a caixa '{c.id}' precisa dar algum recurso "
                             f"(gold, wood ou stone > 0).")
    return crates


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
    unknown = {k for k, _ in START_SWARM_TYPES} - set(zombies)
    if unknown:
        raise StatsError(f"zombies.csv: tipos usados em START_SWARM_TYPES (config.py) não "
                         f"definidos: {', '.join(sorted(unknown))}.")
    waves = _check_waves(read_rows(folder / "waves.csv", WaveRow), zombies)
    for b in buildings.values():
        if b.harvest and (b.harvest not in HARVEST_KINDS or b.harvest_radius < 1
                          or b.harvest_tiles < 1 or b.harvest_max < 1):
            raise StatsError(f"buildings.csv: '{b.id}' tem harvest inválido (use wood/stone com "
                             f"harvest_radius, harvest_tiles e harvest_max >= 1).")
    for kind in ("hq", "infected"):
        if buildings[kind].buildable:
            raise StatsError(f"buildings.csv: '{kind}' não pode ter buildable=1.")
    crates = _check_crates(read_table(folder / "crates.csv", CrateStats))
    heroes = read_table(folder / "heroes.csv", HeroStats)
    _check_ids("heroes.csv", heroes, REQUIRED_HEROES, exact=True)
    skills = read_table(folder / "skills.csv", SkillStats)
    _check_ids("skills.csv", skills, set(SKILL_EFFECTS), exact=True)
    return GameStats(buildings, units, zombies, waves, crates, heroes, _check_skills(skills))


STATS = load_stats()
BUILDING_STATS: dict[str, BuildingStats] = STATS.buildings
UNIT_SPECS: dict[str, UnitStats] = STATS.units
ZOMBIE_SPECS: dict[str, ZombieSpec] = STATS.zombies
# cronograma de ondas (ordenado por turno); direções "?" são sorteadas no início da partida
WAVE_SCHEDULE: list[WaveRow] = STATS.waves
CRATE_SPECS: dict[str, CrateStats] = STATS.crates
HERO_SPECS: dict[str, HeroStats] = STATS.heroes
SKILL_SPECS: dict[str, SkillStats] = STATS.skills
# habilidades de cada herói, na ordem do CSV (atalhos Q, E, R)
HERO_SKILLS: dict[str, list[SkillStats]] = {h: [s for s in SKILL_SPECS.values() if s.hero == h]
                                            for h in HERO_SPECS}
# construções que o jogador pode erguer (botões/atalhos)
BUILD_SPECS: dict[str, BuildingStats] = {k: v for k, v in BUILDING_STATS.items() if v.buildable}
VISION_RADIUS: dict[str, int] = {**{k: v.vision for k, v in BUILDING_STATS.items()},
                                 **{k: v.vision for k, v in UNIT_SPECS.items()}}
