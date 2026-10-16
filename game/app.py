"""Loop principal do Pygame: entrada, atualização e desenho."""
from __future__ import annotations

from typing import Optional

import pygame

from .config import (BUILD_SPECS, CAMERA_PAN_SPEED, COLORS, FPS, GRID_H, GRID_W, HUD_W,
                     VIEW_H, VIEW_W, WINDOW_H, WINDOW_W)
from .grid import Pos
from .hud import HUD
from .renderer import Camera, Renderer, UIState
from .turns import TurnManager
from .world import World

MODE_KEYS = {pygame.K_1: "wall", pygame.K_2: "tent", pygame.K_3: "ballista", pygame.K_4: "repair",
             pygame.K_5: "tesla"}


class GameApp:
    def __init__(self, seed: Optional[int] = None):
        pygame.init()
        pygame.display.set_caption("They Are Thousands - Protótipo Tático")
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        self.clock = pygame.time.Clock()
        self.viewport = pygame.Rect(0, 0, VIEW_W, VIEW_H)
        self.hud = HUD(pygame.Rect(VIEW_W, 0, HUD_W, WINDOW_H))
        self.renderer = Renderer()
        self.running = True
        self._drag_origin: Optional[tuple[int, int]] = None
        self.new_game(seed)

    def new_game(self, seed: Optional[int] = None) -> None:
        self.world = World(seed)
        self.turns = TurnManager(self.world)
        self.camera = Camera(self.viewport, GRID_W, GRID_H)
        self.ui = UIState()

    # ------------------------------------------------------------------
    def run(self, max_frames: Optional[int] = None) -> None:
        frames = 0
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                self.handle_event(event)
            self.update(dt)
            self.draw()
            frames += 1
            if max_frames is not None and frames >= max_frames:
                break
        pygame.quit()

    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.KEYDOWN:
            self._on_key(event)
        elif event.type == pygame.MOUSEWHEEL:
            mouse = pygame.mouse.get_pos()
            if self.viewport.collidepoint(mouse):
                self.camera.zoom_at(mouse, 1.1 if event.y > 0 else 1 / 1.1)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                self._on_left_click(event.pos)
            elif event.button == 3:
                self.cancel()
            elif event.button == 2:
                self._drag_origin = event.pos
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 2:
            self._drag_origin = None
        elif event.type == pygame.MOUSEMOTION and self._drag_origin is not None:
            self.camera.pan(-event.rel[0], -event.rel[1])

    def _on_key(self, event: pygame.event.Event) -> None:
        if event.key == pygame.K_r and (event.mod & pygame.KMOD_CTRL or self.world.game_over):
            self.new_game()
        elif event.key == pygame.K_ESCAPE:
            self.cancel()
        elif event.key in (pygame.K_SPACE, pygame.K_RETURN):
            self.end_turn()
        elif event.key in MODE_KEYS:
            self.set_mode(MODE_KEYS[event.key])

    def cancel(self) -> None:
        self.ui.mode = None
        self.ui.selected_unit = None

    def set_mode(self, mode: str) -> None:
        if not self.turns.is_player_phase:
            return
        self.ui.mode = None if self.ui.mode == mode else mode
        self.ui.selected_unit = None

    def end_turn(self) -> None:
        if self.turns.end_player_turn():
            self.cancel()

    def _on_left_click(self, pos: tuple[int, int]) -> None:
        button = self.hud.button_at(pos)
        if button is not None:
            if button.action == "end_turn":
                self.end_turn()
            else:
                self.set_mode(button.action)
            return
        tile_pos = self.camera.screen_to_tile(pos)
        if tile_pos is not None:
            self._on_tile_click(tile_pos)

    def _on_tile_click(self, pos: Pos) -> None:
        self.ui.selected_tile = pos
        if not self.turns.is_player_phase:
            return
        world = self.world
        tile = world.grid.tile(pos)

        if self.ui.mode in BUILD_SPECS:
            world.build(self.ui.mode, pos)
            return
        if self.ui.mode == "repair":
            world.repair(pos)
            return

        unit = self.ui.selected_unit
        if unit is not None:
            if tile.unit is not None:
                self.ui.selected_unit = None if tile.unit is unit else tile.unit
            elif pos in world.attack_targets(unit):
                world.unit_attack(unit, pos)
            elif pos in world.gather_targets(unit):
                world.unit_gather(unit, pos)
            elif pos in world.unit_moves(unit):
                world.move_unit(unit, pos)
            else:
                self.ui.selected_unit = None
            return
        if tile.unit is not None:
            self.ui.selected_unit = tile.unit

    # ------------------------------------------------------------------
    def update(self, dt: float) -> None:
        keys = pygame.key.get_pressed()
        dx = (keys[pygame.K_d] or keys[pygame.K_RIGHT]) - (keys[pygame.K_a] or keys[pygame.K_LEFT])
        dy = (keys[pygame.K_s] or keys[pygame.K_DOWN]) - (keys[pygame.K_w] or keys[pygame.K_UP])
        if dx or dy:
            self.camera.pan(dx * CAMERA_PAN_SPEED * dt, dy * CAMERA_PAN_SPEED * dt)

        self.turns.update(dt)

        ui = self.ui
        if ui.selected_unit is not None and not ui.selected_unit.alive:
            ui.selected_unit = None
        if not self.turns.is_player_phase:
            ui.mode = None
        ui.hover_tile = self.camera.screen_to_tile(pygame.mouse.get_pos())
        unit = ui.selected_unit
        if unit is not None and self.turns.is_player_phase:
            ui.move_tiles = set(self.world.unit_moves(unit))
            ui.attack_tiles = set(self.world.attack_targets(unit))
            ui.gather_tiles = set(self.world.gather_targets(unit))
        else:
            ui.move_tiles, ui.attack_tiles, ui.gather_tiles = set(), set(), set()

    def draw(self) -> None:
        self.screen.fill(COLORS["bg"])
        self.renderer.draw(self.screen, self.world, self.camera, self.ui)
        self.hud.draw(self.screen, self.world, self.turns, self.ui, pygame.mouse.get_pos())
        if self.world.game_over and not self.turns.busy:
            self._draw_game_over()
        pygame.display.flip()

    def _draw_game_over(self) -> None:
        shade = pygame.Surface(self.viewport.size, pygame.SRCALPHA)
        shade.fill((0, 0, 0, 150))
        self.screen.blit(shade, self.viewport.topleft)
        title = "VITÓRIA" if self.world.victory else "DERROTA"
        color = COLORS["victory"] if self.world.victory else COLORS["defeat"]
        big = self.renderer.font(96).render(title, True, color)
        self.screen.blit(big, big.get_rect(center=(self.viewport.centerx, self.viewport.centery - 40)))
        info = (f"Turno {self.world.turn} | Zumbis abatidos: {self.world.zombies_killed}"
                "   —   Pressione R para jogar novamente")
        small = self.renderer.font(28).render(info, True, COLORS["text"])
        self.screen.blit(small, small.get_rect(center=(self.viewport.centerx, self.viewport.centery + 30)))
