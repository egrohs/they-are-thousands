"""Loop principal do Pygame: entrada, atualização e desenho."""
from __future__ import annotations

from typing import Optional
from pathlib import Path

import pygame

from .config import (CAMERA_PAN_SPEED, COLORS, FOW_ENABLED_DEFAULT, FPS, GRID_H,
                     GRID_W, HUD_W, MUSIC_VOLUME_STEP, NET_PORT, VIEW_H, VIEW_W, WINDOW_H,
                     WINDOW_W)
from .stats import BUILD_SPECS
from .audio import MusicPlayer
from .coop import ClientSession, GameSetup, HostSession, Session
from .editor import EditorScreen
from .entities import Hero
from .grid import Pos
from .heropick import HeroPicker
from .hud import HUD
from .maps import MapError, list_maps, load_map
from .menu import Menu, Settings
from .net import NetError, local_ip
from .renderer import Camera, Renderer, UIState
from .turns import TurnManager
from .world import World

MODE_KEYS = {pygame.K_1: "wall", pygame.K_2: "tent", pygame.K_3: "ballista", pygame.K_4: "repair",
             pygame.K_5: "tesla", pygame.K_6: "watchtower",
             pygame.K_7: "sawmill", pygame.K_8: "quarry"}
RANDOM_MAP_LABEL = "Aleatório"
SKILL_KEYS = (pygame.K_q, pygame.K_e, pygame.K_r)


class GameApp:
    def __init__(self, seed: Optional[int] = None, fog_enabled: bool = FOW_ENABLED_DEFAULT,
                 show_menu: bool = True, music_enabled: bool = True,
                 map_data: Optional[dict] = None, start_in_editor: bool = False):
        pygame.init()
        pygame.display.set_caption("They Are Thousands - Protótipo Tático")
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        self.clock = pygame.time.Clock()
        self.viewport = pygame.Rect(0, 0, VIEW_W, VIEW_H)
        self.hud = HUD(pygame.Rect(VIEW_W, 0, HUD_W, WINDOW_H))
        self.renderer = Renderer()
        self.settings = Settings(fog_enabled=fog_enabled, music_enabled=music_enabled)
        self.music = MusicPlayer(enabled=music_enabled)
        self.settings.music_volume = self.music.volume
        self.settings.music_available = self.music.can_play
        self.music.start()
        self.menu = Menu(self.screen.get_rect())
        self.menu.open = show_menu and not start_in_editor
        self.menu.started = not show_menu
        self.running = True
        self._drag_origin: Optional[tuple[int, int]] = None
        self.map_data: Optional[dict] = None
        self._map_index = 0
        self.set_map(map_data)
        self.editor: Optional[EditorScreen] = None
        self.in_editor = False
        self.camera = Camera(self.viewport, GRID_W, GRID_H)
        self.ui = UIState()
        self.picker = HeroPicker(self.viewport)
        self._local_ip = ""
        self.session: Session = Session(GameSetup.new(seed, self.settings.fog_enabled, self.map_data))
        self._generation = self.session.generation
        if start_in_editor:
            self.open_editor()

    # --- sessão (local ou co-op) ------------------------------------------------
    @property
    def world(self) -> World:
        return self.session.world

    @property
    def turns(self) -> TurnManager:
        return self.session.turns

    @property
    def player_id(self) -> int:
        return self.session.player_id

    @property
    def my_hero(self) -> Optional[Hero]:
        return self.world.hero_of(self.player_id)

    @property
    def picking_hero(self) -> bool:
        """O jogador local ainda não tem herói: a tela de escolha bloqueia o jogo."""
        return self.my_hero is None and not self.world.game_over

    def can_control(self, unit) -> bool:
        return self.world.can_control(unit, self.player_id)

    def pick_hero(self, hero_id: str) -> None:
        if self.world.can_pick_hero(hero_id, self.player_id)[0]:
            self.submit({"op": "hero", "role": hero_id})
            hero = self.my_hero
            if hero is not None:
                self.camera.center_on_tile(hero.pos)

    def new_game(self, seed: Optional[int] = None) -> bool:
        setup = GameSetup.new(seed, self.settings.fog_enabled, self.map_data)
        if not self.session.new_game(setup):
            self.world.message("Co-op: somente o anfitrião pode iniciar uma nova partida.")
            return False
        self._sync_session()
        return True

    def _sync_session(self) -> None:
        """Partida reconstruída (nova, ressincronizada, hospedada...): reseta a UI local."""
        session = self.session
        if session.generation != self._generation:
            self._generation = session.generation
            self.ui = UIState()
            if session.new_game_started:
                self.camera = Camera(self.viewport, GRID_W, GRID_H)
        self.settings.fog_enabled = self.world.fog.enabled
        self.settings.net_role = session.role
        if session.role == "host":
            assert isinstance(session, HostSession)
            n = len(session.player_ids)
            self.settings.net_info = (f"Hospedando: amigos entram em {self._local_ip}:{session.port}"
                                      f"  ({n} jogador(es))")
        elif session.role == "client":
            assert isinstance(session, ClientSession)
            self.settings.net_info = (f"Conectado a {session.host}:{session.port} como "
                                      f"P{session.player_id} ({len(session.player_ids)} jogador(es))")
        else:
            self.settings.net_info = ""

    def start_host(self, port: int = NET_PORT) -> bool:
        if self.session.online:
            return False
        try:
            self.session = HostSession(self.session.setup, port, adopt=self.session)
        except NetError as exc:
            self.settings.net_error = str(exc)
            return False
        self._local_ip = local_ip()
        self.settings.net_error = ""
        self._sync_session()
        return True

    def join(self, address: str) -> bool:
        if self.session.online:
            return False
        try:
            session = ClientSession(address)
        except NetError as exc:
            self.settings.net_error = str(exc)
            return False
        self.session = session
        self.settings.net_error = ""
        self.menu.open = False
        self.menu.started = True
        self._sync_session()
        return True

    def leave_network(self) -> None:
        if not self.session.online:
            return
        self.session.close()
        self.session = Session.detached(self.session)
        self._sync_session()

    def submit(self, cmd: dict) -> None:
        self.session.submit(cmd)
        self._sync_session()

    def set_map(self, data: Optional[dict]) -> None:
        """Define o mapa das próximas partidas (None = gerado aleatoriamente)."""
        self.map_data = data
        self.settings.map_label = str(data.get("name", "?")) if data else RANDOM_MAP_LABEL

    def cycle_map(self, step: int) -> None:
        options: list[Optional[Path]] = [None, *list_maps()]
        for _ in range(len(options)):
            self._map_index = (self._map_index + step) % len(options)
            path = options[self._map_index]
            if path is None:
                self.set_map(None)
                return
            try:
                self.set_map(load_map(path))
                return
            except MapError as exc:
                self.world.message(str(exc))

    # --- editor ------------------------------------------------------------
    def open_editor(self) -> None:
        if self.editor is None:
            self.editor = EditorScreen(self.viewport, self.hud.rect, self.renderer,
                                       on_play=self._play_from_editor, on_exit=self._exit_editor)
        else:
            self.editor.refresh_maps()
        self.cancel()
        self.menu.open = False
        self.in_editor = True

    def _play_from_editor(self, data: dict) -> None:
        self.set_map(data)
        self.new_game()
        self.in_editor = False
        self.menu.open = False
        self.menu.started = True

    def _exit_editor(self) -> None:
        self.in_editor = False
        self.open_menu()

    def set_fog(self, enabled: bool) -> None:
        # comando de jogo: no co-op a névoa é compartilhada (afeta regras como emboscadas)
        self.submit({"op": "fog", "enabled": enabled})

    def open_menu(self) -> None:
        self.cancel()
        self._drag_origin = None
        self.menu.open = True
        self.menu.focus = 0
        self.settings.net_error = ""

    def _on_menu_action(self, action: str) -> None:
        if action == "resume":
            self.menu.open = False
            self.menu.started = True
        elif action == "new_game":
            if self.new_game():
                self.menu.open = False
                self.menu.started = True
            else:
                self.settings.net_error = "Somente o anfitrião pode iniciar uma nova partida."
        elif action == "host":
            self.start_host()
        elif action == "join":
            self.join(self.settings.join_address)
        elif action == "stop_net":
            self.leave_network()
        elif action in ("cycle_map", "cycle_map_back"):
            self.cycle_map(1 if action == "cycle_map" else -1)
        elif action == "open_editor":
            self.open_editor()
        elif action == "toggle_fog":
            self.set_fog(not self.settings.fog_enabled)
        elif action == "toggle_music":
            self.toggle_music()
        elif action in ("volume_up", "volume_down"):
            self.change_volume(MUSIC_VOLUME_STEP if action == "volume_up" else -MUSIC_VOLUME_STEP)
        elif action == "quit":
            self.running = False

    def toggle_music(self) -> None:
        self.music.toggle()
        self.settings.music_enabled = self.music.enabled
        if self.music.error and self.music.enabled:
            self.world.message(self.music.error)

    def change_volume(self, delta: float) -> None:
        self.music.change_volume(delta)
        self.settings.music_volume = self.music.volume

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
        self.session.close()
        pygame.quit()

    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == MusicPlayer.END_EVENT:
            self.music.handle_event(event)
        elif event.type == pygame.QUIT:
            self.running = False
        elif self.menu.open:
            action = self.menu.handle_event(event, self.settings)
            if action is not None:
                self._on_menu_action(action)
        elif self.in_editor and self.editor is not None:
            self.editor.handle_event(event)
        elif self.picking_hero:
            self._on_picker_event(event)
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

    def _on_picker_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.open_menu()
            elif event.key == pygame.K_m:
                self.toggle_music()
            else:
                choice = self.picker.key_choice(event.key)
                if choice is not None:
                    self.pick_hero(choice)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.hud.menu_button.rect.collidepoint(event.pos):
                self.open_menu()
                return
            choice = self.picker.card_at(event.pos)
            if choice is not None:
                self.pick_hero(choice)

    def _on_key(self, event: pygame.event.Event) -> None:
        hero = self._selected_hero()
        if (event.key in SKILL_KEYS and hero is not None and not event.mod & pygame.KMOD_CTRL
                and not self.world.game_over):
            self.activate_skill(SKILL_KEYS.index(event.key))
        elif event.key == pygame.K_r and (event.mod & pygame.KMOD_CTRL or self.world.game_over):
            self.new_game()
        elif event.key == pygame.K_h:
            self.select_my_hero()
        elif event.key == pygame.K_ESCAPE:
            if self.ui.skill:
                self.ui.skill = None
            elif self.ui.mode or self.ui.selected_unit:
                self.cancel()
            else:
                self.open_menu()
        elif event.key == pygame.K_f:
            self.set_fog(not self.settings.fog_enabled)
        elif event.key == pygame.K_g:
            self.renderer.use_sprites = not self.renderer.use_sprites
        elif event.key == pygame.K_m:
            self.toggle_music()
        elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.change_volume(-MUSIC_VOLUME_STEP)
        elif event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            self.change_volume(MUSIC_VOLUME_STEP)
        elif event.key == pygame.K_n:
            self.music.next_track()
        elif event.key in (pygame.K_SPACE, pygame.K_RETURN):
            self.end_turn()
        elif event.key in (pygame.K_z, pygame.K_BACKSPACE):
            self.undo()
        elif event.key in MODE_KEYS:
            self.set_mode(MODE_KEYS[event.key])

    def cancel(self) -> None:
        self.ui.mode = None
        self.ui.skill = None
        self.ui.selected_unit = None

    def _selected_hero(self) -> Optional[Hero]:
        u = self.ui.selected_unit
        return u if isinstance(u, Hero) and self.can_control(u) else None

    def select_my_hero(self) -> None:
        hero = self.my_hero
        if hero is None:
            return
        if hero.state == "recovering":
            self.world.message(f"{hero.name} está convalescendo na base ({hero.recover_turns} turno(s)).")
            return
        self.ui.mode = None
        self.ui.skill = None
        self.ui.selected_unit = hero if hero.alive else None
        self.ui.selected_tile = hero.pos
        self.camera.center_on_tile(hero.pos)

    def activate_skill(self, index: int) -> None:
        """Q/E/R ou botão: habilidades sem alvo são usadas na hora; as demais entram em mira."""
        hero = self._selected_hero()
        if hero is None or not self.turns.is_player_phase:
            return
        skills = self.world.hero_skills(hero)
        if not 0 <= index < len(skills):
            return
        skill = skills[index]
        if self.ui.skill == skill.id:
            self.ui.skill = None
            return
        ok, reason = self.world.skill_status(hero, skill.id)
        if not ok:
            self.world.message(reason)
            return
        if skill.target == "self":
            self.submit({"op": "skill", "skill": skill.id, "from": list(hero.pos), "to": list(hero.pos)})
            self.ui.skill = None
        else:
            self.ui.skill = skill.id
            self.ui.mode = None

    def set_mode(self, mode: str) -> None:
        if not self.turns.is_player_phase:
            return
        self.ui.mode = None if self.ui.mode == mode else mode
        self.ui.skill = None
        self.ui.selected_unit = None

    def undo(self) -> None:
        if self.turns.is_player_phase:
            # unidades restauradas são novas instâncias: update() limpa a seleção órfã
            self.submit({"op": "undo"})

    def end_turn(self) -> None:
        if self.turns.is_player_phase and not self.world.game_over:
            self.submit({"op": "end_turn"})
            self.cancel()

    def _on_left_click(self, pos: tuple[int, int]) -> None:
        button = self.hud.button_at(pos)
        if button is not None:
            if button.action == "end_turn":
                self.end_turn()
            elif button.action == "undo":
                self.undo()
            elif button.action == "menu":
                self.open_menu()
            elif button.action.startswith("skill:"):
                self.activate_skill(int(button.action.split(":")[1]))
            elif button.action == "deselect":
                self.cancel()
            elif button.action == "my_hero":
                self.select_my_hero()
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
            self.submit({"op": "build", "kind": self.ui.mode, "pos": list(pos)})
            return
        if self.ui.mode == "repair":
            self.submit({"op": "repair", "pos": list(pos)})
            return

        unit = self.ui.selected_unit
        if unit is not None and self.ui.skill and isinstance(unit, Hero):
            skill, self.ui.skill = self.ui.skill, None
            if pos in world.skill_targets(unit, skill):
                self.submit({"op": "skill", "skill": skill, "from": list(unit.pos), "to": list(pos)})
            return
        if unit is not None:
            op = None
            if not self.can_control(unit):
                self.ui.selected_unit = tile.unit if tile.unit is not unit else None
            elif pos in world.revive_targets(unit):
                op = "revive"
            elif tile.unit is not None:
                self.ui.selected_unit = None if tile.unit is unit else tile.unit
            elif pos in world.attack_targets(unit):
                op = "attack"
            elif pos in world.gather_targets(unit):
                op = "gather"
            elif pos in world.unit_moves(unit):
                op = "move"
            else:
                self.ui.selected_unit = None
            if op is not None:
                self.submit({"op": op, "from": list(unit.pos), "to": list(pos)})
            return
        if tile.unit is not None:
            self.ui.selected_unit = tile.unit

    # ------------------------------------------------------------------
    def update(self, dt: float) -> None:
        session = self.session
        paused = self.menu.open or self.in_editor
        if session.online or not paused:  # no co-op a partida não pausa no menu/editor
            session.update(dt)
        if session.online and not session.connected:
            self.leave_network()
            self.settings.net_error = "Conexão com o anfitrião perdida."
        self._sync_session()
        ui = self.ui
        ui.net_status = self.session.status
        ui.peer_cursors = self.session.peer_cursors
        if paused:
            self.session.send_cursor(None)
            if self.in_editor and self.editor is not None and not self.menu.open:
                self.editor.update(dt, CAMERA_PAN_SPEED)
            return
        keys = pygame.key.get_pressed()
        dx = (keys[pygame.K_d] or keys[pygame.K_RIGHT]) - (keys[pygame.K_a] or keys[pygame.K_LEFT])
        dy = (keys[pygame.K_s] or keys[pygame.K_DOWN]) - (keys[pygame.K_w] or keys[pygame.K_UP])
        if dx or dy:
            self.camera.pan(dx * CAMERA_PAN_SPEED * dt, dy * CAMERA_PAN_SPEED * dt)

        unit = ui.selected_unit
        if unit is not None and (not unit.alive or self.world.grid.tile(unit.pos).unit is not unit):
            ui.selected_unit = None  # morta, ou substituída por desfazer/ressincronização
        if not self.turns.is_player_phase:
            ui.mode = None
            ui.skill = None
        ui.player_id = self.player_id
        ui.hover_tile = self.camera.screen_to_tile(pygame.mouse.get_pos())
        self.session.send_cursor(ui.hover_tile)
        unit = ui.selected_unit
        if unit is not None and self.turns.is_player_phase and self.can_control(unit):
            ui.move_tiles = set(self.world.unit_moves(unit))
            ui.attack_tiles = set(self.world.attack_targets(unit))
            ui.gather_tiles = set(self.world.gather_targets(unit))
            ui.revive_tiles = set(self.world.revive_targets(unit))
            if ui.skill and isinstance(unit, Hero):
                ui.skill_tiles = set(self.world.skill_targets(unit, ui.skill))
                if not ui.skill_tiles:
                    ui.skill = None
                ui.move_tiles, ui.attack_tiles, ui.gather_tiles = set(), set(), set()
            else:
                ui.skill, ui.skill_tiles = None, set()
        else:
            ui.move_tiles, ui.attack_tiles, ui.gather_tiles = set(), set(), set()
            ui.revive_tiles, ui.skill_tiles, ui.skill = set(), set(), None

    def draw(self) -> None:
        self.screen.fill(COLORS["bg"])
        if self.in_editor and self.editor is not None:
            self.editor.draw(self.screen, pygame.mouse.get_pos())
        else:
            self.renderer.draw(self.screen, self.world, self.camera, self.ui)
            self.hud.draw(self.screen, self.world, self.turns, self.ui, pygame.mouse.get_pos())
            if self.world.game_over and not self.turns.busy:
                self._draw_game_over()
            elif self.picking_hero and not self.menu.open:
                self.picker.draw(self.screen, self.world, self.player_id, pygame.mouse.get_pos())
        if self.menu.open:
            self.menu.draw(self.screen, self.settings,
                           self.music.current_track if self.music.playing else None)
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
                f" | Caixas: {self.world.crates_found}/{self.world.crates_total}"
                "   —   Pressione R para jogar novamente")
        small = self.renderer.font(28).render(info, True, COLORS["text"])
        self.screen.blit(small, small.get_rect(center=(self.viewport.centerx, self.viewport.centery + 30)))
        y = self.viewport.centery + 64
        for h in self.world.heroes:
            text = (f"P{h.owner or '-'} {h.name} ({h.role}) - nível {h.level}, {h.xp} XP, "
                    f"{h.kills} abate(s)")
            img = self.renderer.font(24).render(text, True, h.color)
            self.screen.blit(img, img.get_rect(center=(self.viewport.centerx, y)))
            y += 26
