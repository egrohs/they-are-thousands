"""Câmera (offset + zoom) e renderização do tabuleiro com primitivas geométricas."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import pygame

from .config import (COLORS, EXHAUSTED_TINT, INFECTED_TINT, TILE_SIZE, WAVE_EDGE_SPREAD,
                     WAVE_WARNING_TURNS, ZOMBIE_TINTS)
from .entities import Building, Unit, ZombieSwarm
from .grid import Pos, Terrain
from .sprites import SpriteManager
from .stats import BUILD_SPECS, DIRECTION_NAMES
from .world import World, edge_pos


def swarm_sprite_key(kind: str) -> str:
    return f"zombie_{kind}"


@dataclass
class UIState:
    """Dados de interação calculados pela aplicação a cada frame."""
    hover_tile: Optional[Pos] = None
    selected_tile: Optional[Pos] = None
    selected_unit: Optional[Unit] = None
    mode: Optional[str] = None  # "wall" | "tent" | "ballista" | "tesla" | "repair"
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

    def __init__(self, sprites: Optional[SpriteManager] = None):
        self._fonts: dict[int, pygame.font.Font] = {}
        self._overlays: dict[tuple, pygame.Surface] = {}
        self.sprites = sprites if sprites is not None else SpriteManager()
        self.use_sprites = True

    def _sprite(self, surface: pygame.Surface, key: str, rect: pygame.Rect,
                tint=None) -> Optional[pygame.Rect]:
        """Desenha o sprite recortado dentro do tile; retorna o retângulo usado ou None."""
        if not self.use_sprites:
            return None
        inner = rect.inflate(-2, -2)
        img = self.sprites.get(key, min(inner.w, inner.h), tint)
        if img is None:
            return None
        dest = img.get_rect(center=inner.center)
        surface.blit(img, dest)
        return dest

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
        if world.fog.enabled:
            self._draw_fog(surface, world, cam, visible)

        self._draw_overlays(surface, world, cam, ui)
        self._draw_territory_border(surface, world, cam)

        fog = world.fog
        for t in visible:
            rect = cam.tile_rect(t.pos)
            if t.building is not None:
                self._draw_building(surface, rect, t.building, ts)
            if t.unit is not None:
                self._draw_unit(surface, rect, t.unit, ts, t.unit is ui.selected_unit)
            if t.swarm is not None and fog.is_visible(t.pos):
                self._draw_swarm(surface, rect, t.swarm, ts)

        self._draw_pending_noise(surface, world, cam)
        self._draw_wave_warning(surface, world, cam)

        for eff in world.effects:
            if not (fog.is_visible(eff.start) or fog.is_visible(eff.end)):
                continue
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

    def _draw_fog(self, surface, world: World, cam: Camera, tiles) -> None:
        fog = world.fog
        for t in tiles:
            if t.pos in fog.visible:
                continue
            rect = cam.tile_rect(t.pos)
            if t.pos in fog.explored:
                self._overlay(surface, rect, COLORS["fog_explored"], 150)
            else:
                pygame.draw.rect(surface, COLORS["fog_unexplored"], rect)

    def _draw_territory_border(self, surface, world: World, cam: Camera) -> None:
        zone = world.build_zone()
        color = COLORS["territory"]
        for x, y in zone:
            r = cam.tile_rect((x, y))
            if (x, y - 1) not in zone:
                pygame.draw.line(surface, color, r.topleft, (r.right - 1, r.top), 2)
            if (x, y + 1) not in zone:
                pygame.draw.line(surface, color, (r.left, r.bottom - 1), (r.right - 1, r.bottom - 1), 2)
            if (x - 1, y) not in zone:
                pygame.draw.line(surface, color, r.topleft, (r.left, r.bottom - 1), 2)
            if (x + 1, y) not in zone:
                pygame.draw.line(surface, color, (r.right - 1, r.top), (r.right - 1, r.bottom - 1), 2)

    def _draw_building(self, surface, rect: pygame.Rect, b: Building, ts) -> None:
        tint = INFECTED_TINT if b.kind == "infected" else None
        dest = self._sprite(surface, b.kind, rect, tint)
        if dest is not None:
            border = COLORS["zombie_aggr"] if b.hostile else (0, 0, 0)
            pygame.draw.rect(surface, border, dest, 2)
            self._hp_bar(surface, rect, b.hp, b.max_hp)
            return
        inner = rect.inflate(-max(2, int(ts * 0.1)), -max(2, int(ts * 0.1)))
        pygame.draw.rect(surface, COLORS[b.color_key], inner, border_radius=max(1, int(ts * 0.08)))
        pygame.draw.rect(surface, (0, 0, 0), inner, 2, border_radius=max(1, int(ts * 0.08)))
        if b.hostile:
            pygame.draw.line(surface, (40, 70, 10), inner.topleft, inner.bottomright, 2)
            pygame.draw.line(surface, (40, 70, 10), inner.topright, inner.bottomleft, 2)
        self._text(surface, b.symbol, (inner.centerx, inner.centery - int(ts * 0.06)), ts * 0.5)
        self._hp_bar(surface, rect, b.hp, b.max_hp)

    def _draw_unit(self, surface, rect: pygame.Rect, u: Unit, ts, selected: bool) -> None:
        dest = self._sprite(surface, u.kind, rect, EXHAUSTED_TINT if u.exhausted else None)
        if dest is not None:
            border = COLORS["select"] if selected else COLORS[u.color_key]
            pygame.draw.rect(surface, border, dest, 3 if selected else 2)
        else:
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
        border = COLORS["zombie_noise"] if s.noise_target is not None else (0, 0, 0)
        dest = self._sprite(surface, swarm_sprite_key(s.kind), rect, ZOMBIE_TINTS.get(s.kind))
        if dest is not None:
            if s.aggressive and s.noise_target is None:
                border = COLORS["zombie_aggr"]
            pygame.draw.rect(surface, border, dest, 2)
            r = max(5, int(ts * 0.2))
            badge = (dest.right - r, dest.bottom - r)
            pygame.draw.circle(surface, COLORS["zombie_aggr"] if s.aggressive else COLORS["zombie_idle"],
                               badge, r)
            pygame.draw.circle(surface, (0, 0, 0), badge, r, 1)
            self._text(surface, str(s.count), badge, r * 1.7)
            tag = pygame.Rect(dest.x + 2, dest.y + 2, r * 2, r * 2)
            pygame.draw.rect(surface, s.spec.color, tag, border_radius=3)
            pygame.draw.rect(surface, (0, 0, 0), tag, 1, border_radius=3)
            self._text(surface, s.spec.symbol, tag.center, r * 1.7)
            return
        inner = rect.inflate(-max(2, int(ts * 0.14)), -max(2, int(ts * 0.14)))
        pygame.draw.rect(surface, s.spec.color, inner)
        if s.aggressive and s.noise_target is None:
            border = COLORS["zombie_aggr"]
        pygame.draw.rect(surface, border, inner, 2)
        self._text(surface, f"{s.spec.symbol}{s.count}", inner.center, ts * 0.5)

    def _draw_pending_noise(self, surface, world: World, cam: Camera) -> None:
        for ev in world.pending_noise:
            c = cam.tile_rect(ev.pos).center
            r = ev.radius * cam.tile_px + cam.tile_px / 2
            pts = [(c[0], c[1] - r), (c[0] + r, c[1]), (c[0], c[1] + r), (c[0] - r, c[1])]
            pygame.draw.polygon(surface, COLORS["noise"], pts, 1)

    def _draw_wave_warning(self, surface, world: World, cam: Camera) -> None:
        """Faixa vermelha na borda de entrada + seta (ou seta na borda da tela se fora de vista)."""
        wave = world.next_wave
        if wave is None:
            return
        left = wave.turn - world.turn
        if left > WAVE_WARNING_TURNS:
            return
        blink = left == 0 and (pygame.time.get_ticks() // 400) % 2 == 0
        color = COLORS["wave_warning"]
        ts = cam.tile_px
        label = ("HORDA" if wave.final else "ONDA") + ("!" if left == 0 else f" em {left}")
        view = cam.viewport
        for side, anchor in wave.entry_points:
            along0 = anchor[0] if side in (0, 1) else anchor[1]
            length = world.grid.width if side in (0, 1) else world.grid.height
            for along in range(max(0, along0 - WAVE_EDGE_SPREAD),
                               min(length, along0 + WAVE_EDGE_SPREAD + 1)):
                rect = cam.tile_rect(edge_pos(side, along))
                if rect.colliderect(view):
                    self._overlay(surface, rect, color, 120 if blink else 70)
            inward = {0: (0, 1), 1: (0, -1), 2: (1, 0), 3: (-1, 0)}[side]
            c = cam.tile_rect(anchor).center
            base = (c[0] - inward[0] * ts * 0.4, c[1] - inward[1] * ts * 0.4)
            tip = (base[0] + inward[0] * ts * 1.6, base[1] + inward[1] * ts * 1.6)
            if view.inflate(-int(ts), -int(ts)).collidepoint(c):
                self._arrow(surface, base, tip, max(10, ts * 0.7), color)
                text_at = (tip[0] + inward[0] * ts * 0.6, tip[1] + inward[1] * ts * 0.6)
                if side in (2, 3):  # bordas laterais: texto acima da seta
                    text_at = (base[0] + inward[0] * ts * 1.4, base[1] - ts * 0.8)
                self._label(surface, label, text_at, max(16, ts * 0.6), color, view)
                continue
            # entrada fora da tela: seta presa à borda da viewport apontando para ela
            box = view.inflate(-44, -44)
            px = min(max(c[0], box.left), box.right)
            py = min(max(c[1], box.top), box.bottom)
            dx, dy = c[0] - px, c[1] - py
            dist = math.hypot(dx, dy) or 1.0
            ux, uy = dx / dist, dy / dist
            self._arrow(surface, (px - ux * 18, py - uy * 18), (px + ux * 14, py + uy * 14), 16, color)
            self._label(surface, f"{label} ({DIRECTION_NAMES[side]})",
                        (px - ux * 30, py - uy * 30 + (0 if abs(uy) > 0.5 else -18)), 18, color, view)

    def _label(self, surface, text: str, center, size, color, view: pygame.Rect) -> None:
        """Texto com fundo escuro, mantido dentro da viewport."""
        img = self.font(size).render(text, True, color)
        rect = img.get_rect(center=(round(center[0]), round(center[1]))).inflate(8, 4)
        rect.clamp_ip(view.inflate(-4, -4))
        self._overlay(surface, rect, (0, 0, 0), 160)
        surface.blit(img, img.get_rect(center=rect.center))

    @staticmethod
    def _arrow(surface, start, end, width, color) -> None:
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        head = min(length * 0.6, width * 1.1)
        neck = (end[0] - ux * head, end[1] - uy * head)
        shaft = width * 0.22
        pts = [(start[0] + px * shaft, start[1] + py * shaft),
               (neck[0] + px * shaft, neck[1] + py * shaft),
               (neck[0] + px * width / 2, neck[1] + py * width / 2),
               end,
               (neck[0] - px * width / 2, neck[1] - py * width / 2),
               (neck[0] - px * shaft, neck[1] - py * shaft),
               (start[0] - px * shaft, start[1] - py * shaft)]
        pygame.draw.polygon(surface, color, pts)
        pygame.draw.polygon(surface, (0, 0, 0), pts, 1)
