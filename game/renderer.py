"""Câmera (offset + zoom) e renderização do tabuleiro com primitivas geométricas."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import pygame

from .config import BUILD_SPECS, COLORS, TILE_SIZE
from .entities import Building, Unit, ZombieSwarm
from .grid import Pos, Terrain
from .world import World


@dataclass
class UIState:
    """Dados de interação calculados pela aplicação a cada frame."""
    hover_tile: Optional[Pos] = None
    selected_tile: Optional[Pos] = None
    selected_unit: Optional[Unit] = None
    mode: Optional[str] = None  # "wall" | "tent" | "ballista" | "repair"
    move_tiles: set[Pos] = field(default_factory=set)
    attack_tiles: set[Pos] = field(default_factory=set)
    gather_tiles: set[Pos] = field(default_factory=set)


class Camera:
    MIN_ZOOM = 0.5
    MAX_ZOOM = 2.5
    MARGIN_TILES = 2

    def __init__(self, viewport: pygame.Rect, grid_w: int, grid_h: int):
        self.viewport = viewport
        self.map_px = (grid_w * TILE_SIZE, grid_h * TILE_SIZE)
        self.grid_size = (grid_w, grid_h)
        self.zoom = 1.0
        self.x = 0.0  # canto superior esquerdo visível, em px do mundo (zoom 1)
        self.y = 0.0
        self.center_on_tile((grid_w / 2, grid_h / 2))

    @property
    def tile_px(self) -> float:
        return TILE_SIZE * self.zoom

    def _clamp(self) -> None:
        margin = self.MARGIN_TILES * TILE_SIZE
        for axis, view in ((0, self.viewport.w), (1, self.viewport.h)):
            visible = view / self.zoom
            size = self.map_px[axis]
            if visible >= size + 2 * margin:
                value = (size - visible) / 2
            else:
                current = self.x if axis == 0 else self.y
                value = max(-margin, min(size - visible + margin, current))
            if axis == 0:
                self.x = value
            else:
                self.y = value

    def center_on_tile(self, pos: tuple[float, float]) -> None:
        self.x = pos[0] * TILE_SIZE - self.viewport.w / 2 / self.zoom
        self.y = pos[1] * TILE_SIZE - self.viewport.h / 2 / self.zoom
        self._clamp()

    def pan(self, dx: float, dy: float) -> None:
        self.x += dx / self.zoom
        self.y += dy / self.zoom
        self._clamp()

    def screen_to_world(self, sp: tuple[int, int]) -> tuple[float, float]:
        return (self.x + (sp[0] - self.viewport.x) / self.zoom,
                self.y + (sp[1] - self.viewport.y) / self.zoom)

    def zoom_at(self, sp: tuple[int, int], factor: float) -> None:
        wx, wy = self.screen_to_world(sp)
        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.zoom * factor))
        self.x = wx - (sp[0] - self.viewport.x) / self.zoom
        self.y = wy - (sp[1] - self.viewport.y) / self.zoom
        self._clamp()

    def screen_to_tile(self, sp: tuple[int, int]) -> Optional[Pos]:
        if not self.viewport.collidepoint(sp):
            return None
        wx, wy = self.screen_to_world(sp)
        tx, ty = math.floor(wx / TILE_SIZE), math.floor(wy / TILE_SIZE)
        if 0 <= tx < self.grid_size[0] and 0 <= ty < self.grid_size[1]:
            return (tx, ty)
        return None

    def tile_rect(self, pos: Pos) -> pygame.Rect:
        vx, vy = self.viewport.topleft
        left = round(vx + (pos[0] * TILE_SIZE - self.x) * self.zoom)
        top = round(vy + (pos[1] * TILE_SIZE - self.y) * self.zoom)
        right = round(vx + ((pos[0] + 1) * TILE_SIZE - self.x) * self.zoom)
        bottom = round(vy + ((pos[1] + 1) * TILE_SIZE - self.y) * self.zoom)
        return pygame.Rect(left, top, right - left, bottom - top)


class Renderer:
    TERRAIN_COLORS = {
        Terrain.GRASS: COLORS["grass"],
        Terrain.FOREST: COLORS["forest"],
        Terrain.ROCK: COLORS["rock"],
        Terrain.WATER: COLORS["water"],
    }

    def __init__(self):
        self._fonts: dict[int, pygame.font.Font] = {}
        self._overlays: dict[tuple, pygame.Surface] = {}

    def font(self, size: int) -> pygame.font.Font:
        size = max(8, int(size))
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(None, size)
        return self._fonts[size]

    def _overlay(self, surface: pygame.Surface, rect: pygame.Rect,
                 color: tuple[int, int, int], alpha: int) -> None:
        key = (rect.w, rect.h, color, alpha)
        surf = self._overlays.get(key)
        if surf is None:
            surf = pygame.Surface((max(1, rect.w), max(1, rect.h)), pygame.SRCALPHA)
            surf.fill((*color, alpha))
            if len(self._overlays) > 512:
                self._overlays.clear()
            self._overlays[key] = surf
        surface.blit(surf, rect.topleft)

    def _text(self, surface: pygame.Surface, text: str, center: tuple[int, int], size: int,
              color=(255, 255, 255), shadow: bool = True) -> None:
        f = self.font(size)
        if shadow:
            s = f.render(text, True, (0, 0, 0))
            surface.blit(s, s.get_rect(center=(center[0] + 1, center[1] + 1)))
        img = f.render(text, True, color)
        surface.blit(img, img.get_rect(center=center))

    def _hp_bar(self, surface: pygame.Surface, rect: pygame.Rect, hp: int, max_hp: int) -> None:
        h = max(3, rect.h // 9)
        bar = pygame.Rect(rect.x + 2, rect.bottom - h - 2, rect.w - 4, h)
        pygame.draw.rect(surface, COLORS["hp_bg"], bar)
        ratio = max(0.0, hp / max_hp) if max_hp else 0
        fill = bar.copy()
        fill.w = round(bar.w * ratio)
        pygame.draw.rect(surface, COLORS["hp_fg"] if ratio > 0.4 else COLORS["hp_low"], fill)

    # ------------------------------------------------------------------
    def draw(self, surface: pygame.Surface, world: World, cam: Camera, ui: UIState) -> None:
        surface.set_clip(cam.viewport)
        surface.fill(COLORS["bg"], cam.viewport)
        ts = cam.tile_px
        grid = world.grid

        visible = [t for t in grid if cam.tile_rect(t.pos).colliderect(cam.viewport)]

        for t in visible:
            self._draw_terrain(surface, cam.tile_rect(t.pos), t.terrain, t.resource_amount, ts)

        self._draw_overlays(surface, world, cam, ui)

        for t in visible:
            rect = cam.tile_rect(t.pos)
            if t.building is not None:
                self._draw_building(surface, rect, t.building, ts)
            if t.unit is not None:
                self._draw_unit(surface, rect, t.unit, ts, t.unit is ui.selected_unit)
            if t.swarm is not None:
                self._draw_swarm(surface, rect, t.swarm, ts)

        self._draw_pending_noise(surface, world, cam)

        for eff in world.effects:
            a = cam.tile_rect(eff.start).center
            b = cam.tile_rect(eff.end).center
            pygame.draw.line(surface, COLORS[eff.color_key], a, b, max(2, int(ts / 12)))
            pygame.draw.circle(surface, COLORS[eff.color_key], b, max(3, int(ts / 8)), 2)

        if ui.selected_tile is not None:
            pygame.draw.rect(surface, COLORS["select"], cam.tile_rect(ui.selected_tile), 2)
        if ui.hover_tile is not None:
            pygame.draw.rect(surface, COLORS["hover"], cam.tile_rect(ui.hover_tile), 1)
        surface.set_clip(None)

    def _draw_terrain(self, surface, rect, terrain, amount, ts) -> None:
        pygame.draw.rect(surface, self.TERRAIN_COLORS[terrain], rect)
        pygame.draw.rect(surface, COLORS["grid_line"], rect, 1)
        cx, cy = rect.center
        if terrain is Terrain.FOREST:
            r = ts * 0.22
            for ox in (-0.18, 0.18):
                x = cx + ox * ts
                pygame.draw.polygon(surface, COLORS["tree"], [
                    (x, cy - r * 1.4), (x - r, cy + r * 0.6), (x + r, cy + r * 0.6)])
        elif terrain is Terrain.ROCK:
            r = ts * 0.22
            pygame.draw.polygon(surface, COLORS["stone_icon"], [
                (cx - r, cy + r * 0.6), (cx - r * 0.4, cy - r), (cx + r * 0.6, cy - r * 0.6),
                (cx + r, cy + r * 0.6)])
        if terrain.resource and ts >= 20:
            f = self.font(ts * 0.4)
            img = f.render(str(amount), True, COLORS["gold"])
            surface.blit(img, (rect.right - img.get_width() - 2, rect.top + 1))

    def _draw_overlays(self, surface, world: World, cam: Camera, ui: UIState) -> None:
        for p, level in world.noise_map.items():
            self._overlay(surface, cam.tile_rect(p), COLORS["noise"], min(110, 18 + 14 * level))

        if ui.mode in BUILD_SPECS:
            zone = world.build_zone()
            for p in zone:
                ok, _ = world.can_build(ui.mode, p, zone)
                self._overlay(surface, cam.tile_rect(p),
                              COLORS["build_ok"] if ok else COLORS["build_bad"], 55 if ok else 25)
        elif ui.mode == "repair":
            for b in world.grid.buildings():
                if world.can_repair(b.pos)[0]:
                    self._overlay(surface, cam.tile_rect(b.pos), COLORS["build_ok"], 90)

        for p in ui.move_tiles:
            self._overlay(surface, cam.tile_rect(p), COLORS["move"], 80)
        for p in ui.gather_tiles:
            pygame.draw.rect(surface, COLORS["gather"], cam.tile_rect(p).inflate(-2, -2), 2)
        for p in ui.attack_tiles:
            rect = cam.tile_rect(p)
            self._overlay(surface, rect, COLORS["attack"], 70)
            pygame.draw.rect(surface, COLORS["attack"], rect, 2)

        if ui.selected_unit is not None and ui.selected_unit.alive:
            u = ui.selected_unit
            r = u.attack_range
            tl = cam.tile_rect((u.pos[0] - r, u.pos[1] - r)).topleft
            br = cam.tile_rect((u.pos[0] + r, u.pos[1] + r)).bottomright
            pygame.draw.rect(surface, COLORS["attack"], pygame.Rect(tl, (br[0] - tl[0], br[1] - tl[1])), 1)

    def _draw_building(self, surface, rect: pygame.Rect, b: Building, ts) -> None:
        inner = rect.inflate(-max(2, int(ts * 0.1)), -max(2, int(ts * 0.1)))
        pygame.draw.rect(surface, COLORS[b.color_key], inner, border_radius=max(1, int(ts * 0.08)))
        pygame.draw.rect(surface, (0, 0, 0), inner, 2, border_radius=max(1, int(ts * 0.08)))
        if b.hostile:
            pygame.draw.line(surface, (40, 70, 10), inner.topleft, inner.bottomright, 2)
            pygame.draw.line(surface, (40, 70, 10), inner.topright, inner.bottomleft, 2)
        self._text(surface, b.symbol, (inner.centerx, inner.centery - int(ts * 0.06)), ts * 0.5)
        self._hp_bar(surface, rect, b.hp, b.max_hp)

    def _draw_unit(self, surface, rect: pygame.Rect, u: Unit, ts, selected: bool) -> None:
        radius = int(ts * 0.36)
        center = (rect.centerx, rect.centery - int(ts * 0.04))
        color = COLORS[u.color_key]
        if u.exhausted:
            color = tuple(c // 2 for c in color)
        pygame.draw.circle(surface, color, center, radius)
        pygame.draw.circle(surface, COLORS["select"] if selected else (0, 0, 0), center, radius,
                           3 if selected else 2)
        self._text(surface, u.symbol, center, ts * 0.5)
        dot = max(2, int(ts * 0.07))
        if not u.moved:
            pygame.draw.circle(surface, COLORS["move"], (rect.left + dot + 2, rect.top + dot + 2), dot)
        if not u.acted:
            pygame.draw.circle(surface, COLORS["attack"], (rect.right - dot - 2, rect.top + dot + 2), dot)
        self._hp_bar(surface, rect, u.hp, u.max_hp)

    def _draw_swarm(self, surface, rect: pygame.Rect, s: ZombieSwarm, ts) -> None:
        inner = rect.inflate(-max(2, int(ts * 0.14)), -max(2, int(ts * 0.14)))
        color = COLORS["zombie_aggr"] if s.aggressive else COLORS["zombie_idle"]
        pygame.draw.rect(surface, color, inner)
        border = COLORS["zombie_noise"] if s.noise_target is not None else (0, 0, 0)
        pygame.draw.rect(surface, border, inner, 2)
        self._text(surface, str(s.count), inner.center, ts * 0.62)

    def _draw_pending_noise(self, surface, world: World, cam: Camera) -> None:
        for ev in world.pending_noise:
            c = cam.tile_rect(ev.pos).center
            r = ev.radius * cam.tile_px + cam.tile_px / 2
            pts = [(c[0], c[1] - r), (c[0] + r, c[1]), (c[0], c[1] + r), (c[0] - r, c[1])]
            pygame.draw.polygon(surface, COLORS["noise"], pts, 1)
