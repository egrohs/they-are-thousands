"""HUD lateral: recursos, fase, botões de ação, inspeção de tile e log."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pygame

from .config import (COLORS, MAX_TURNS, REPAIR_AMOUNT, REPAIR_AP,
                     REPAIR_WOOD,                      RESOURCE_LABELS)
from .grid import Pos
from .renderer import UIState
from .stats import BUILDING_STATS
from .turns import TurnManager
from .world import World


@dataclass
class Button:
    rect: pygame.Rect
    label: str
    action: str
    sub_label: str = ""

    def draw(self, surface: pygame.Surface, fonts: "HUD", hovered: bool, active: bool,
             enabled: bool, base_color: Optional[tuple[int, int, int]] = None) -> None:
        if not enabled:
            color = COLORS["button_disabled"]
        elif active:
            color = COLORS["button_active"]
        elif hovered:
            color = COLORS["button_hover"]
        else:
            color = base_color or COLORS["button"]
        pygame.draw.rect(surface, color, self.rect, border_radius=6)
        pygame.draw.rect(surface, COLORS["hud_border"], self.rect, 1, border_radius=6)
        text_color = COLORS["text"] if enabled else COLORS["text_dim"]
        label = fonts.font(22).render(self.label, True, text_color)
        if self.sub_label:
            surface.blit(label, (self.rect.x + 8, self.rect.y + 4))
            sub = fonts.font(17).render(self.sub_label, True, COLORS["text_dim"])
            surface.blit(sub, (self.rect.x + 8, self.rect.bottom - sub.get_height() - 4))
        else:
            surface.blit(label, label.get_rect(center=self.rect.center))


def wave_status(world: World) -> str:
    wave = world.next_wave
    if wave is None:
        return "Sem novas ondas programadas"
    left = wave.turn - world.turn
    when = "neste turno!" if left == 0 else f"em {left} turno(s)"
    label = "HORDA FINAL" if wave.final else "Onda"
    return f"{label}: {wave.directions} ~{wave.zombies} - {when}"


def _name(kind: str) -> str:
    return BUILDING_STATS[kind].name


def _cost_text(kind: str) -> str:
    spec = BUILDING_STATS[kind]
    parts = [f"{spec.ap} AP"]
    parts += [f"{v} {RESOURCE_LABELS[k][:2]}" for k, v in spec.cost.items() if v]
    return " | ".join(parts) + f" | HP {spec.hp}"


def wrap_text(font: pygame.font.Font, text: str, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        candidate = f"{line} {w}".strip()
        if font.size(candidate)[0] <= width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


class HUD:
    def __init__(self, rect: pygame.Rect):
        self.rect = rect
        self._fonts: dict[int, pygame.font.Font] = {}
        x, w = rect.x + 12, rect.w - 24
        half = (w - 8) // 2
        y = 168
        self.buttons: list[Button] = [
            Button(pygame.Rect(x, y, half, 44), f"[1] {_name('wall')}", "wall", _cost_text("wall")),
            Button(pygame.Rect(x + half + 8, y, half, 44), f"[2] {_name('tent')}", "tent", _cost_text("tent")),
            Button(pygame.Rect(x, y + 50, half, 44), f"[3] {_name('ballista')}", "ballista", _cost_text("ballista")),
            Button(pygame.Rect(x + half + 8, y + 50, half, 44), "[4] Reparar", "repair",
                   f"{REPAIR_AP} AP | {REPAIR_WOOD} Ma | +{REPAIR_AMOUNT} HP"),
            Button(pygame.Rect(x, y + 100, half, 44), f"[5] {_name('tesla')} (território)", "tesla",
                   _cost_text("tesla") + f" | r{BUILDING_STATS['tesla'].build_radius}"),
            Button(pygame.Rect(x + half + 8, y + 100, half, 44), f"[6] {_name('watchtower')}",
                   "watchtower", _cost_text("watchtower")),
            Button(pygame.Rect(x, y + 152, w, 38), "Encerrar Turno  [Espaço]", "end_turn"),
        ]
        self.info_top = y + 202
        self.menu_button = Button(pygame.Rect(rect.right - 84, 10, 72, 26), "Menu", "menu")

    def font(self, size: int) -> pygame.font.Font:
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(None, size)
        return self._fonts[size]

    def button_at(self, pos: tuple[int, int]) -> Optional[Button]:
        if self.menu_button.rect.collidepoint(pos):
            return self.menu_button
        return next((b for b in self.buttons if b.rect.collidepoint(pos)), None)

    def _line(self, surface, text: str, pos: tuple[int, int], size: int = 22,
              color=COLORS["text"]) -> int:
        img = self.font(size).render(text, True, color)
        surface.blit(img, pos)
        return pos[1] + img.get_height() + 3

    def draw(self, surface: pygame.Surface, world: World, turns: TurnManager, ui: UIState,
             mouse_pos: tuple[int, int]) -> None:
        pygame.draw.rect(surface, COLORS["hud_bg"], self.rect)
        pygame.draw.line(surface, COLORS["hud_border"], self.rect.topleft, self.rect.bottomleft, 2)
        x = self.rect.x + 12
        y = self._line(surface, "THEY ARE THOUSANDS", (x, 10), 30, COLORS["title"])
        where = f"Mapa: {world.map_name}" if world.map_name else f"Seed {world.seed}"
        y = self._line(surface, f"Turno {world.turn}/{MAX_TURNS}   {where}", (x, y), 22)
        phase_color = COLORS["text"] if turns.is_player_phase else COLORS["noise"]
        y = self._line(surface, f"Fase: {turns.phase.value}", (x, y), 22, phase_color)

        res_y = y + 2
        col = x
        for key in ("gold", "wood", "stone"):
            txt = f"{RESOURCE_LABELS[key]}: {world.resources[key]}"
            img = self.font(22).render(txt, True, COLORS[key])
            surface.blit(img, (col, res_y))
            col += img.get_width() + 14
        y = res_y + 22
        y = self._line(surface, f"AP: {world.ap}", (x, y), 26, COLORS["ap"])
        if world.fog.enabled:
            zombies = f"Zumbis à vista: {world.visible_zombies}"
        else:
            zombies = f"Zumbis: {world.total_zombies}"
        final = world.final_wave
        if world.final_horde_spawned:
            horde = "Horda final em campo!"
        elif final is not None:
            horde = f"Horda final: turno {final.turn}"
        else:
            horde = ""
        y = self._line(surface, f"{zombies}   {horde}", (x, y), 19, COLORS["defeat"])
        self._line(surface, wave_status(world), (x, y), 19, COLORS["wave_warning"])

        enabled = turns.is_player_phase and not world.game_over
        for b in self.buttons:
            b.draw(surface, self, b.rect.collidepoint(mouse_pos), ui.mode == b.action, enabled,
                   COLORS["end_turn"] if b.action == "end_turn" else None)
        self.menu_button.draw(surface, self, self.menu_button.rect.collidepoint(mouse_pos),
                              False, True)

        y = self._draw_info(surface, world, ui, x, self.info_top)
        self._draw_log(surface, world, x, y + 8)

    def _draw_info(self, surface, world: World, ui: UIState, x: int, y: int) -> int:
        y = self._line(surface, "Inspeção", (x, y), 22, COLORS["title"])
        pos: Optional[Pos] = ui.hover_tile or ui.selected_tile
        lines: list[tuple[str, tuple[int, int, int]]] = []
        if ui.selected_unit is not None:
            u = ui.selected_unit
            lines.append((f"Selecionado: {u.name} HP {u.hp}/{u.max_hp}", COLORS[u.color_key]))
            shelter = world.shelter_of(u)
            if shelter is not None:
                lines.append((f"Abrigado na {shelter.name}: protegido, +{shelter.range_bonus} alc., "
                               f"+{shelter.vision_bonus} visão", COLORS["watchtower"]))
            lines.append((f"Mov {u.move_range}{' (usado)' if u.moved else ''} | Alc {world.unit_range(u)}"
                          f" | Dano {u.damage} | Ruído {u.noise}"
                          f"{' | agiu' if u.acted else ''}", COLORS["text_dim"]))
        if pos is not None and not world.fog.is_explored(pos):
            lines.append((f"Tile {pos}: Inexplorado", COLORS["text_dim"]))
        elif pos is not None:
            t = world.grid.tile(pos)
            seen = world.fog.is_visible(pos)
            terrain = t.terrain.label
            if t.terrain.resource:
                terrain += f" ({RESOURCE_LABELS[t.terrain.resource]} {t.resource_amount})"
            if not seen:
                terrain += " — sob névoa"
            lines.append((f"Tile {pos}: {terrain}", COLORS["text"]))
            if t.building is not None:
                b = t.building
                lines.append((f"{b.name} HP {b.hp}/{b.max_hp}", COLORS[b.color_key]))
                if b.garrison:
                    guest = world.garrisoned(b)
                    lines.append((f"Abriga: {guest.name}" if guest else
                                  f"Vazia: mova uma unidade para cá (+{b.range_bonus} alcance, "
                                  f"+{b.vision_bonus} visão, protegida)", COLORS["text_dim"]))
            if t.unit is not None and t.unit is not ui.selected_unit:
                lines.append((f"{t.unit.name} HP {t.unit.hp}/{t.unit.max_hp}", COLORS[t.unit.color_key]))
            if t.swarm is not None and seen:
                s = t.swarm
                state = "agressivo" if s.aggressive else "ocioso"
                if s.noise_target is not None:
                    state = f"atraído por som em {s.noise_target}"
                sp = s.spec
                lines.append((f"{sp.name} x{s.count}/{s.max_stack} ({state})",
                              COLORS["zombie_aggr"]))
                hp = f"HP {sp.hp}" + (f" (-{s.wounds})" if s.wounds else "")
                lines.append((f"{hp} | Vel {sp.speed} | Dano {s.attack_power}"
                              f"{f' | Alc {sp.attack_range}' if sp.attack_range > 1 else ''}",
                              COLORS["text_dim"]))
                lines.append((sp.description, COLORS["text_dim"]))
            level = world.noise_map.get(pos, 0)
            if level:
                lines.append((f"Ruído no último turno: {level}", COLORS["noise"]))
        if ui.mode:
            lines.append(("Clique no mapa para aplicar. Botão direito/Esc cancela.", COLORS["text_dim"]))
        elif ui.selected_unit is not None:
            lines.append(("Azul: mover | Vermelho: atacar | Amarelo: coletar", COLORS["text_dim"]))
        width = self.rect.w - 24
        for text, color in lines:
            for part in wrap_text(self.font(19), text, width):
                y = self._line(surface, part, (x, y), 19, color)
        return y

    def _draw_log(self, surface, world: World, x: int, y: int) -> None:
        y = self._line(surface, "Eventos", (x, y), 22, COLORS["title"])
        bottom = self.rect.bottom - 44
        width = self.rect.w - 24
        font = self.font(18)
        wrapped: list[str] = []
        for entry in world.log:
            wrapped.extend(wrap_text(font, entry, width))
        line_h = font.get_linesize()
        max_lines = max(0, (bottom - y) // line_h)
        for line in wrapped[-max_lines:] if max_lines else []:
            surface.blit(font.render(line, True, COLORS["text_dim"]), (x, y))
            y += line_h
        help_text = "WASD: câmera | Roda: zoom | M: música | -/+: volume | Esc: menu"
        surface.blit(self.font(17).render(help_text, True, COLORS["text_dim"]),
                     (x, self.rect.bottom - 22))
