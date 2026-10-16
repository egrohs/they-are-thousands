"""Editor de mapas: lógica de edição (`MapEditor`) e tela (`EditorScreen`).

`MapEditor` não desenha nada e é testável sem janela; `EditorScreen` cuida de entrada,
painel lateral e desenho reaproveitando o `Renderer` do jogo.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import pygame

from .config import COLORS, GRID_H, GRID_W, MAPS_DIR, MAX_SWARM_SIZE
from .entities import CommandCenter, ZombieSwarm
from .grid import Pos, Terrain
from .stats import CRATE_SPECS, ZOMBIE_SPECS
from .hud import Button, wrap_text
from .maps import (MAP_BUILDINGS, MAP_UNITS, MapError, build_grid, grid_to_data, list_maps,
                   load_map, save_map)
from .renderer import Camera, Renderer, UIState
from .world import World

UNDO_LIMIT = 60
DEFAULT_NAME = "Novo mapa"
MAX_NAME_LEN = 24

TERRAIN_TOOLS = {"t:grass": Terrain.GRASS, "t:forest": Terrain.FOREST,
                 "t:rock": Terrain.ROCK, "t:water": Terrain.WATER}
TOOL_LABELS: dict[str, str] = {
    "t:grass": "Campo", "t:forest": "Floresta", "t:rock": "Pedreira", "t:water": "Água",
    "b:hq": "CC", "b:tent": "Tenda", "b:wall": "Muro", "b:ballista": "Balista",
    "b:tesla": "Tesla", "b:watchtower": "Torre Vigia", "b:infected": "Casa Inf.",
    "u:soldier": "Soldado", "u:ranger": "Ranger",
    **{f"z:{k}": spec.name for k, spec in ZOMBIE_SPECS.items()},
    **{f"c:{k}": spec.name.split()[0] for k, spec in CRATE_SPECS.items()},
    "erase": "Borracha",
}


def blank_map_data(name: str = DEFAULT_NAME) -> dict[str, Any]:
    cx, cy = GRID_W // 2, GRID_H // 2
    return {"version": 1, "name": name, "width": GRID_W, "height": GRID_H,
            "terrain": ["G" * GRID_W] * GRID_H, "resources": [],
            "buildings": [{"kind": "hq", "pos": [cx, cy]}], "units": [], "swarms": [],
            "crates": []}


class MapEditor:
    """Estado de edição sobre um `World` (névoa desligada) com desfazer/refazer."""

    def __init__(self, data: Optional[dict[str, Any]] = None):
        self.tool = "t:forest"
        self.amount = 5          # zumbis por enxame / quantidade do depósito de recurso
        self.brush = 1           # 1 = 1x1, 3 = 3x3 (terreno e borracha)
        self.status = ""
        self.undo_stack: list[dict[str, Any]] = []
        self.redo_stack: list[dict[str, Any]] = []
        self.dirty = False
        self._stroke_snapshot: Optional[dict[str, Any]] = None
        self._stroke_changed = False
        self._set_data(data or blank_map_data())

    # --- dados -----------------------------------------------------------
    def _set_data(self, data: dict[str, Any]) -> None:
        self.name = str(data.get("name") or DEFAULT_NAME)[:MAX_NAME_LEN]
        self.world = World(seed=0, fog_enabled=False, map_data=data)

    def to_data(self) -> dict[str, Any]:
        return grid_to_data(self.world.grid, self.name)

    def _replace(self, data: dict[str, Any], status: str) -> None:
        self._push_undo(self.to_data())
        self._set_data(data)
        self.dirty = True
        self.status = status

    def new_blank(self) -> None:
        self._replace(blank_map_data(), "Mapa vazio criado.")

    def generate(self, seed: Optional[int] = None) -> None:
        w = World(seed, fog_enabled=False)
        data = grid_to_data(w.grid, self.name)
        self._replace(data, f"Mapa aleatório gerado (seed {w.seed}).")

    def load(self, path: Path) -> bool:
        try:
            data = load_map(path)
        except MapError as exc:
            self.status = str(exc)
            return False
        self._replace(data, f"Mapa '{data['name']}' carregado.")
        self.dirty = False
        return True

    def save(self, folder: Path = MAPS_DIR) -> Optional[Path]:
        try:
            path = save_map(self.to_data(), folder)
        except (MapError, OSError) as exc:
            self.status = f"Erro ao salvar: {exc}"
            return None
        self.dirty = False
        self.status = f"Salvo em maps/{path.name}"
        return path

    def validate(self) -> Optional[str]:
        try:
            build_grid(self.to_data())
        except MapError as exc:
            return str(exc)
        return None

    def rename(self, name: str) -> None:
        name = name.strip()[:MAX_NAME_LEN]
        if name and name != self.name:
            self.name = name
            self.dirty = True

    # --- desfazer --------------------------------------------------------
    def _push_undo(self, snapshot: dict[str, Any]) -> None:
        self.undo_stack.append(snapshot)
        del self.undo_stack[:-UNDO_LIMIT]
        self.redo_stack.clear()

    def undo(self) -> bool:
        if not self.undo_stack:
            self.status = "Nada para desfazer."
            return False
        self.redo_stack.append(self.to_data())
        self._set_data(self.undo_stack.pop())
        self.dirty = True
        self.status = "Desfeito."
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            self.status = "Nada para refazer."
            return False
        self.undo_stack.append(self.to_data())
        self._set_data(self.redo_stack.pop())
        self.dirty = True
        self.status = "Refeito."
        return True

    def begin_stroke(self) -> None:
        self._stroke_snapshot = self.to_data()
        self._stroke_changed = False

    def end_stroke(self) -> None:
        if self._stroke_snapshot is not None and self._stroke_changed:
            self._push_undo(self._stroke_snapshot)
        self._stroke_snapshot = None
        self._stroke_changed = False

    # --- pintura ---------------------------------------------------------
    def set_amount(self, value: int) -> None:
        self.amount = max(1, min(MAX_SWARM_SIZE, value))

    def brush_tiles(self, pos: Pos) -> list[Pos]:
        if self.tool in TERRAIN_TOOLS or self.tool == "erase":
            return self.world.grid.tiles_in_radius(pos, self.brush // 2, "chebyshev")
        return [pos]

    def apply(self, pos: Pos, tool: Optional[str] = None) -> bool:
        """Aplica a ferramenta (ou `tool`) em `pos`. Retorna True se algo mudou."""
        tool = tool or self.tool
        grid = self.world.grid
        if not grid.in_bounds(pos):
            return False
        if tool in TERRAIN_TOOLS or tool == "erase":
            radius = self.brush // 2
            targets = grid.tiles_in_radius(pos, radius, "chebyshev")
        else:
            targets = [pos]
        changed = False
        for p in targets:
            changed |= self._apply_one(p, tool)
        if changed:
            self.dirty = True
            self._stroke_changed = True
        return changed

    def _apply_one(self, pos: Pos, tool: str) -> bool:
        tile = self.world.grid.tile(pos)
        is_hq = isinstance(tile.building, CommandCenter)
        if tool in TERRAIN_TOOLS:
            terrain = TERRAIN_TOOLS[tool]
            amount = self.amount if terrain.resource else 0
            if tile.terrain is terrain and tile.resource_amount == amount:
                return False
            if is_hq and terrain is not Terrain.GRASS:
                self.status = "O CC só fica em Campo; mova-o antes."
                return False
            if not terrain.passable:
                tile.building = tile.unit = tile.swarm = tile.crate = None
            tile.terrain, tile.resource_amount = terrain, amount
            return True
        if tool == "erase":
            if tile.swarm is not None:
                tile.swarm = None
            elif tile.unit is not None:
                tile.unit = None
            elif tile.crate:
                tile.crate = None
            elif tile.building is not None and not is_hq:
                tile.building = None
            elif is_hq:
                self.status = "O Centro de Comando não pode ser apagado (mova-o)."
                return False
            elif tile.terrain is not Terrain.GRASS:
                tile.terrain, tile.resource_amount = Terrain.GRASS, 0
            else:
                return False
            return True
        if is_hq and tool != "b:hq":
            self.status = "Tile ocupado pelo Centro de Comando."
            return False
        category, kind = tool.split(":", 1)
        if category == "b":
            return self._place_building(pos, kind)
        if not tile.terrain.passable:
            self.status = f"Unidades e zumbis não ficam em {tile.terrain.label}."
            return False
        if category == "c":
            if tile.crate == kind:
                return False
            tile.building = tile.unit = None
            tile.crate = kind
            return True
        if category == "u":
            if tile.unit is not None and tile.unit.kind == kind:
                return False
            tile.building = tile.swarm = tile.crate = None
            tile.unit = MAP_UNITS[kind](pos)
            return True
        if category == "z":
            s = tile.swarm
            count = min(self.amount, ZOMBIE_SPECS[kind].max_stack)
            if s is not None and s.kind == kind and s.count == count:
                return False
            tile.building = tile.unit = None
            tile.swarm = ZombieSwarm(pos, count, kind=kind)
            return True
        return False

    def _place_building(self, pos: Pos, kind: str) -> bool:
        grid = self.world.grid
        tile = grid.tile(pos)
        if tile.building is not None and tile.building.kind == kind:
            return False
        tile.building = tile.unit = tile.swarm = tile.crate = None
        tile.terrain, tile.resource_amount = Terrain.GRASS, 0
        if kind == "hq":
            grid.remove_building(self.world.hq)
            self.world.hq = CommandCenter(pos)
            grid.place_building(self.world.hq)
        else:
            grid.place_building(MAP_BUILDINGS[kind](pos))
        return True

    def describe(self, pos: Pos) -> list[str]:
        t = self.world.grid.tile(pos)
        terrain = t.terrain.label + (f" ({t.resource_amount})" if t.terrain.resource else "")
        lines = [f"Tile {pos}: {terrain}"]
        if t.building is not None:
            lines.append(t.building.name)
        if t.unit is not None:
            lines.append(t.unit.name)
        if t.swarm is not None:
            lines.append(f"{t.swarm.name} x{t.swarm.count}")
        if t.crate and t.crate in CRATE_SPECS:
            lines.append(f"Caixa: {CRATE_SPECS[t.crate].name} ({World.loot_text(t.crate)})")
        return lines


# ============================================================================
@dataclass
class _Section:
    title: str
    y: int


class EditorScreen:
    """Tela do editor. `on_play(data)` inicia uma partida; `on_exit()` volta ao menu."""

    def __init__(self, viewport: pygame.Rect, panel: pygame.Rect, renderer: Renderer,
                 on_play: Callable[[dict[str, Any]], None], on_exit: Callable[[], None],
                 maps_dir: Path = MAPS_DIR):
        self.viewport = viewport
        self.panel = panel
        self.renderer = renderer
        self.on_play = on_play
        self.on_exit = on_exit
        self.maps_dir = Path(maps_dir)
        self.editor = MapEditor()
        self.camera = Camera(viewport, GRID_W, GRID_H)
        self.ui = UIState()
        self._fonts: dict[int, pygame.font.Font] = {}
        self._paint_button: Optional[int] = None
        self._last_paint: Optional[Pos] = None
        self._drag_origin: Optional[tuple[int, int]] = None
        self.renaming: Optional[str] = None
        self.saved_maps: list[Path] = []
        self.map_buttons: list[tuple[Button, Path]] = []
        self._build_layout()
        self.refresh_maps()

    # --- layout ----------------------------------------------------------
    def font(self, size: int) -> pygame.font.Font:
        size = max(8, int(size))
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(None, size)
        return self._fonts[size]

    def _row(self, y: int, items: list[tuple[str, str]], cols: int, h: int = 28) -> int:
        x0, w = self.panel.x + 12, self.panel.w - 24
        bw = (w - (cols - 1) * 6) // cols
        for i, (action, label) in enumerate(items):
            r, c = divmod(i, cols)
            rect = pygame.Rect(x0 + c * (bw + 6), y + r * (h + 4), bw, h)
            self.buttons.append(Button(rect, label, action))
        rows = (len(items) + cols - 1) // cols
        return y + rows * (h + 4)

    def _build_layout(self) -> None:
        self.buttons: list[Button] = []
        self.sections: list[_Section] = []
        x0, w = self.panel.x + 12, self.panel.w - 24
        self.name_button = Button(pygame.Rect(x0, 42, w, 28), "", "rename")
        y = 76

        def section(title: str) -> int:
            self.sections.append(_Section(title, y))
            return y + 18

        tools = lambda keys: [(k, TOOL_LABELS[k]) for k in keys]  # noqa: E731
        y = section("Terreno")
        y = self._row(y, tools(TERRAIN_TOOLS), 4) + 4
        y = section("Construções")
        y = self._row(y, tools(["b:hq", "b:tent", "b:wall", "b:ballista", "b:tesla", "b:watchtower",
                                "b:infected"]), 3) + 4
        y = section("Unidades / Zumbis")
        y = self._row(y, tools(["u:soldier", "u:ranger", "erase"]
                               + [f"z:{k}" for k in ZOMBIE_SPECS]), 3) + 4
        y = section("Caixas de recursos")
        y = self._row(y, tools([f"c:{k}" for k in CRATE_SPECS]), 3, 24) + 4
        y = self._row(y, [("amount_down", "-"), ("amount_up", "+"), ("brush", "Pincel")], 3) + 4
        y = self._row(y, [("undo", "Desfazer"), ("redo", "Refazer"), ("new", "Vazio"),
                          ("generate", "Aleatório")], 4)
        y = self._row(y, [("save", "Salvar"), ("play", "Jogar [F5]"), ("exit", "Menu")], 3) + 4
        self.maps_top = y
        self.info_top = self.panel.bottom - 112

    def refresh_maps(self) -> None:
        self.saved_maps = list_maps(self.maps_dir)
        x0, w = self.panel.x + 12, self.panel.w - 24
        y = self.maps_top + 20
        self.map_buttons = []
        for path in self.saved_maps:
            if y + 22 > self.info_top - 6:
                break
            self.map_buttons.append((Button(pygame.Rect(x0, y, w, 22), path.stem, "load"), path))
            y += 25

    # --- entrada ---------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if self.renaming is not None and event.type == pygame.KEYDOWN:
            self._on_rename_key(event)
            return
        if event.type == pygame.KEYDOWN:
            self._on_key(event)
        elif event.type == pygame.MOUSEWHEEL:
            mouse = pygame.mouse.get_pos()
            if self.viewport.collidepoint(mouse):
                self.camera.zoom_at(mouse, 1.1 if event.y > 0 else 1 / 1.1)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 2:
                self._drag_origin = event.pos
            elif event.button in (1, 3):
                self._on_mouse_down(event.pos, event.button)
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 2:
                self._drag_origin = None
            elif event.button == self._paint_button:
                self._end_paint()
        elif event.type == pygame.MOUSEMOTION:
            if self._drag_origin is not None:
                self.camera.pan(-event.rel[0], -event.rel[1])
            elif self._paint_button is not None:
                self._paint_at(event.pos)

    def _on_key(self, event: pygame.event.Event) -> None:
        ctrl = event.mod & pygame.KMOD_CTRL
        ed = self.editor
        if ctrl and event.key == pygame.K_z:
            ed.undo()
        elif ctrl and event.key == pygame.K_y:
            ed.redo()
        elif ctrl and event.key == pygame.K_s:
            self.action("save")
        elif event.key == pygame.K_F5:
            self.action("play")
        elif event.key == pygame.K_ESCAPE:
            self.action("exit")
        elif event.key in (pygame.K_LEFTBRACKET, pygame.K_MINUS, pygame.K_KP_MINUS):
            ed.set_amount(ed.amount - 1)
        elif event.key in (pygame.K_RIGHTBRACKET, pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            ed.set_amount(ed.amount + 1)
        elif event.key == pygame.K_b:
            self.action("brush")
        elif event.key == pygame.K_g:
            self.renderer.use_sprites = not self.renderer.use_sprites

    def _on_rename_key(self, event: pygame.event.Event) -> None:
        assert self.renaming is not None
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.editor.rename(self.renaming)
            self.renaming = None
        elif event.key == pygame.K_ESCAPE:
            self.renaming = None
        elif event.key == pygame.K_BACKSPACE:
            self.renaming = self.renaming[:-1]
        elif event.unicode and event.unicode.isprintable() and len(self.renaming) < MAX_NAME_LEN:
            self.renaming += event.unicode

    def _on_mouse_down(self, pos: tuple[int, int], button: int) -> None:
        if self.renaming is not None:
            self.editor.rename(self.renaming)
            self.renaming = None
        if self.panel.collidepoint(pos):
            if button == 1:
                self._click_panel(pos)
            return
        if self.camera.screen_to_tile(pos) is None:
            return
        self._paint_button = button
        self._last_paint = None
        self.editor.begin_stroke()
        self._paint_at(pos)

    def _paint_at(self, screen_pos: tuple[int, int]) -> None:
        tile = self.camera.screen_to_tile(screen_pos)
        if tile is None or tile == self._last_paint:
            return
        self._last_paint = tile
        self.editor.apply(tile, "erase" if self._paint_button == 3 else None)

    def _end_paint(self) -> None:
        self.editor.end_stroke()
        self._paint_button = None
        self._last_paint = None

    def _click_panel(self, pos: tuple[int, int]) -> None:
        if self.name_button.rect.collidepoint(pos):
            self.renaming = self.editor.name
            return
        for b in self.buttons:
            if b.rect.collidepoint(pos):
                self.action(b.action)
                return
        for b, path in self.map_buttons:
            if b.rect.collidepoint(pos):
                if self.editor.load(path):
                    self.camera = Camera(self.viewport, GRID_W, GRID_H)
                return

    def action(self, action: str) -> None:
        ed = self.editor
        if action in TOOL_LABELS:
            ed.tool = action
        elif action == "amount_down":
            ed.set_amount(ed.amount - 1)
        elif action == "amount_up":
            ed.set_amount(ed.amount + 1)
        elif action == "brush":
            ed.brush = 3 if ed.brush == 1 else 1
        elif action == "undo":
            ed.undo()
        elif action == "redo":
            ed.redo()
        elif action == "new":
            ed.new_blank()
        elif action == "generate":
            ed.generate()
        elif action == "save":
            if ed.save(self.maps_dir) is not None:
                self.refresh_maps()
        elif action == "play":
            error = ed.validate()
            if error:
                ed.status = error
            else:
                self.on_play(ed.to_data())
        elif action == "exit":
            self._end_paint()
            self.on_exit()

    # --- atualização / desenho -------------------------------------------
    def update(self, dt: float, pan_speed: float) -> None:
        if self.renaming is None:
            keys = pygame.key.get_pressed()
            dx = (keys[pygame.K_d] or keys[pygame.K_RIGHT]) - (keys[pygame.K_a] or keys[pygame.K_LEFT])
            dy = (keys[pygame.K_s] or keys[pygame.K_DOWN]) - (keys[pygame.K_w] or keys[pygame.K_UP])
            if dx or dy:
                self.camera.pan(dx * pan_speed * dt, dy * pan_speed * dt)
        self.ui.hover_tile = self.camera.screen_to_tile(pygame.mouse.get_pos())

    def draw(self, surface: pygame.Surface, mouse_pos: tuple[int, int]) -> None:
        self.renderer.draw(surface, self.editor.world, self.camera, self.ui)
        if self.ui.hover_tile is not None:
            surface.set_clip(self.viewport)
            for p in self.editor.brush_tiles(self.ui.hover_tile):
                pygame.draw.rect(surface, COLORS["build_ok"], self.camera.tile_rect(p), 2)
            surface.set_clip(None)
        self._draw_panel(surface, mouse_pos)

    def _line(self, surface, text: str, pos: tuple[int, int], size: int = 20,
              color=COLORS["text"]) -> int:
        img = self.font(size).render(text, True, color)
        surface.blit(img, pos)
        return pos[1] + img.get_height() + 2

    def _draw_panel(self, surface: pygame.Surface, mouse_pos: tuple[int, int]) -> None:
        ed = self.editor
        pygame.draw.rect(surface, COLORS["hud_bg"], self.panel)
        pygame.draw.line(surface, COLORS["hud_border"], self.panel.topleft, self.panel.bottomleft, 2)
        x = self.panel.x + 12
        title = "EDITOR DE MAPAS" + ("  *" if ed.dirty else "")
        self._line(surface, title, (x, 12), 30, COLORS["title"])

        nb = self.name_button
        nb.label = (f"Nome: {self.renaming}_" if self.renaming is not None
                    else f"Nome: {ed.name}  (clique p/ renomear)")
        nb.draw(surface, self, nb.rect.collidepoint(mouse_pos), self.renaming is not None, True)

        for s in self.sections:
            self._line(surface, s.title, (x, s.y), 19, COLORS["text_dim"])
        for b in self.buttons:
            if b.action == "brush":
                b.label = f"Pincel {ed.brush}x{ed.brush} [B]"
            elif b.action == "amount_down":
                b.label = f"- Qtd {ed.amount}"
            elif b.action == "amount_up":
                b.label = f"+ Qtd {ed.amount}"
            color = None
            if b.action.startswith("z:"):
                color = ZOMBIE_SPECS[b.action[2:]].color
            elif b.action.startswith("c:"):
                color = tuple(int(c * 0.55) for c in CRATE_SPECS[b.action[2:]].color)
            elif b.action == "play":
                color = COLORS["button_active"]
            b.draw(surface, self, b.rect.collidepoint(mouse_pos), b.action == ed.tool, True, color)

        self._line(surface, f"Mapas salvos ({len(self.saved_maps)}) - clique p/ carregar",
                   (x, self.maps_top), 19, COLORS["text_dim"])
        if not self.saved_maps:
            self._line(surface, "Nenhum ainda. Use Salvar (Ctrl+S).", (x, self.maps_top + 22),
                       18, COLORS["text_dim"])
        for b, _ in self.map_buttons:
            b.draw(surface, self, b.rect.collidepoint(mouse_pos), False, True)
        hidden = len(self.saved_maps) - len(self.map_buttons)
        if hidden > 0:
            self._line(surface, f"+{hidden} mapa(s) em maps/", (x, self.info_top - 22), 18,
                       COLORS["text_dim"])

        y = self.info_top
        width = self.panel.w - 24
        lines: list[tuple[str, tuple[int, int, int]]] = []
        if self.ui.hover_tile is not None:
            lines.append((" | ".join(ed.describe(self.ui.hover_tile)), COLORS["text"]))
        if ed.status:
            lines.append((ed.status, COLORS["noise"]))
        for text, color in lines:
            for part in wrap_text(self.font(18), text, width):
                y = self._line(surface, part, (x, y), 18, color)
        hint = "Esq: pintar/arrastar | Dir: apagar | Ctrl+Z/Y | Ctrl+S | [ ] qtd | Esc: menu"
        for i, part in enumerate(reversed(wrap_text(self.font(17), hint, width))):
            img = self.font(17).render(part, True, COLORS["text_dim"])
            surface.blit(img, (x, self.panel.bottom - 20 - i * 16))
