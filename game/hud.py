"""HUD lateral: recursos, fase, botões de ação, inspeção de tile e log."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pygame

from .config import (COLORS, HERO_REVIVE_AP, MAX_TURNS, REPAIR_AMOUNT, REPAIR_AP,
                     REPAIR_WOOD, RESOURCE_LABELS)
from .entities import Hero
from .grid import Pos
from .renderer import UIState, unit_color
from .stats import BUILDING_STATS, CRATE_SPECS, HERO_SPECS
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
            font = fonts.font(17)
            text, max_w = self.sub_label, self.rect.w - 16
            if font.size(text)[0] > max_w:
                while text and font.size(text + "…")[0] > max_w:
                    text = text[:-1]
                text = text.rstrip() + "…"
            sub = font.render(text, True, COLORS["text_dim"])
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


def t_label(resource: str) -> str:
    return {"wood": "Floresta", "stone": "Pedreira"}.get(resource, resource)


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
            Button(pygame.Rect(x, y + 150, half, 44), f"[7] {_name('sawmill')}", "sawmill",
                   _cost_text("sawmill")),
            Button(pygame.Rect(x + half + 8, y + 150, half, 44), f"[8] {_name('quarry')}",
                   "quarry", _cost_text("quarry")),
            Button(pygame.Rect(x, y + 202, 118, 38), "Desfazer [Z]", "undo"),
            Button(pygame.Rect(x + 126, y + 202, w - 126, 38), "Encerrar Turno  [Espaço]", "end_turn"),
        ]
        self.info_top = y + 250
        self.menu_button = Button(pygame.Rect(rect.right - 84, 10, 72, 26), "Menu", "menu")
        self.active_buttons: list[Button] = self.buttons
        self._skill_rows = [pygame.Rect(x, y + 50 * i, w, 44) for i in range(3)]
        self._hero_row = (pygame.Rect(x, y + 150, half, 44), pygame.Rect(x + half + 8, y + 150, half, 44))

    def _hero_buttons(self, world: World, hero: Hero) -> list[Button]:
        buttons: list[Button] = []
        for i, (skill, rect) in enumerate(zip(world.hero_skills(hero), self._skill_rows)):
            cost = [f"{skill.ap} AP"]
            if skill.mana:
                cost.append(f"{skill.mana} mana")
            cd = hero.cooldown(skill.id)
            cost.append(f"recarga {cd}" if cd else
                        (f"recarga {skill.cooldown}t" if skill.cooldown else "sem recarga"))
            buttons.append(Button(rect, f"[{'QER'[i]}] {skill.name}", f"skill:{i}",
                                  " | ".join(cost) + f" - {skill.notes}"))
        buttons.append(Button(self._hero_row[0], "[H] Meu herói", "my_hero"))
        buttons.append(Button(self._hero_row[1], "Construções [Esc]", "deselect"))
        return buttons

    def font(self, size: int) -> pygame.font.Font:
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(None, size)
        return self._fonts[size]

    def button_at(self, pos: tuple[int, int]) -> Optional[Button]:
        if self.menu_button.rect.collidepoint(pos):
            return self.menu_button
        return next((b for b in self.active_buttons if b.rect.collidepoint(pos)), None)

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
        if ui.net_status:
            img = self.font(18).render(ui.net_status, True, COLORS["territory"])
            surface.blit(img, img.get_rect(topright=(self.rect.right - 12, y + 3)))
        y = self._line(surface, f"Fase: {turns.phase.value}", (x, y), 22, phase_color)

        res_y = y + 2
        col = x
        prod = world.production()
        for key in ("gold", "wood", "stone"):
            txt = f"{RESOURCE_LABELS[key]}: {world.resources[key]}"
            img = self.font(22).render(txt, True, COLORS[key])
            surface.blit(img, (col, res_y))
            col += img.get_width() + 3
            delta = self.font(17).render(f"(+{prod[key]})", True, COLORS["text_dim"])
            surface.blit(delta, (col, res_y + 4))
            col += delta.get_width() + 10
        y = res_y + 22
        if world.crates_total:
            self._line(surface, f"Caixas: {world.crates_found}/{world.crates_total}",
                       (x + 110, y + 5), 20, COLORS["gold"])
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
        hero = ui.selected_unit if isinstance(ui.selected_unit, Hero) else None
        if hero is not None:
            self.active_buttons = self._hero_buttons(world, hero) + self.buttons[-2:]
        else:
            self.active_buttons = self.buttons
        mine = hero is not None and world.can_control(hero, ui.player_id)
        for b in self.active_buttons:
            on = enabled and (world.can_undo if b.action == "undo" else True)
            active = ui.mode == b.action
            if b.action.startswith("skill:") and hero is not None:
                skill = world.hero_skills(hero)[int(b.action.split(":")[1])]
                on = enabled and mine and world.skill_status(hero, skill.id)[0]
                active = ui.skill == skill.id
            if b.action == "undo":
                b.label = f"Desfazer ({len(world.history)})" if world.history else "Desfazer [Z]"
            b.draw(surface, self, b.rect.collidepoint(mouse_pos), active, on,
                   COLORS["end_turn"] if b.action == "end_turn" else None)
        self.menu_button.draw(surface, self, self.menu_button.rect.collidepoint(mouse_pos),
                              False, True)

        y = self._draw_info(surface, world, ui, x, self.info_top)
        self._draw_log(surface, world, x, y + 8)

    def _hero_state(self, world: World, h: Hero) -> str:
        if h.state == "downed":
            return f"CAÍDO ({h.downed_turns}t p/ resgate)"
        if h.state == "recovering":
            return f"na base ({h.recover_turns}t)"
        extra = f" Abatido {h.debuff_turns}t" if h.debuffed else ""
        return f"HP {h.hp}/{h.max_hp}{extra}"

    def _hero_lines(self, world: World, h: Hero) -> list[tuple[str, tuple[int, int, int]]]:
        xp, nxt = world.xp_progress(h)
        owner = f"P{h.owner}" if h.owner else "sem dono"
        lines = [(f"{h.name} ({h.role}, {owner}) Nv {h.level} - XP {xp}"
                  + (f"/{nxt}" if nxt is not None else " (máx.)"), h.color)]
        stats = (f"HP {h.hp}/{h.max_hp} | Armadura {h.armor} | Mov {h.move_range}"
                 f"{' (usado)' if h.moved else ''} | Alc {world.unit_range(h)} | Dano {h.damage}")
        if h.max_mana:
            stats += f" | Mana {h.mana}/{h.max_mana}"
        lines.append((stats, COLORS["text_dim"]))
        status = []
        if h.downed:
            status.append(f"Caído: um aliado adjacente o levanta ({HERO_REVIVE_AP} AP), "
                          f"{h.downed_turns} turno(s) restantes")
        if h.stealthed:
            status.append(f"Furtivo {h.stealth_turns}t")
        if h.guard_armor:
            status.append(f"Defesa +{h.guard_armor}")
        if h.debuffed:
            status.append(f"Abatido {h.debuff_turns}t (-1 dano, -1 mov)")
        if h.acted:
            status.append("agiu")
        if status:
            lines.append((" | ".join(status), COLORS["skill"]))
        return lines

    def _draw_info(self, surface, world: World, ui: UIState, x: int, y: int) -> int:
        if world.heroes:
            y = self._line(surface, "Heróis", (x, y), 22, COLORS["title"])
            for h in world.heroes:
                owner = f"P{h.owner}" if h.owner else "--"
                y = self._line(surface, f"{owner} {h.name} Nv{h.level}  {self._hero_state(world, h)}",
                               (x, y), 18, h.color)
            y += 4
        y = self._line(surface, "Inspeção", (x, y), 22, COLORS["title"])
        pos: Optional[Pos] = ui.hover_tile or ui.selected_tile
        lines: list[tuple[str, tuple[int, int, int]]] = []
        if isinstance(ui.selected_unit, Hero):
            lines += self._hero_lines(world, ui.selected_unit)
        elif ui.selected_unit is not None:
            u = ui.selected_unit
            lines.append((f"Selecionado: {u.name} HP {u.hp}/{u.max_hp}", unit_color(u)))
            shelter = world.shelter_of(u)
            if shelter is not None:
                lines.append((f"Abrigado na {shelter.name}: protegido, +{shelter.range_bonus} alc., "
                               f"+{shelter.vision_bonus} visão", COLORS["watchtower"]))
            lines.append((f"Mov {u.move_range}{' (usado)' if u.moved else ''} | Alc {world.unit_range(u)}"
                          f" | Dano {u.damage} | Ruído {u.noise}"
                          f"{' | agiu' if u.acted else ''}", COLORS["text_dim"]))
        if (pos is not None and ui.mode in BUILDING_STATS and BUILDING_STATS[ui.mode].harvest
                and world.fog.is_known(pos)):
            tiles, amount = world.harvest_preview(ui.mode, pos)
            spec = BUILDING_STATS[ui.mode]
            lines.append((f"{spec.name} aqui: {len(tiles)} tile(s) livre(s) de "
                          f"{t_label(spec.harvest)} -> +{amount} {RESOURCE_LABELS[spec.harvest]}/turno",
                          COLORS[ui.mode]))
        if pos is not None and world.fog.is_dark(pos):
            lines.append((f"Tile {pos}: Escuridão - nenhum aliado por perto", COLORS["text_dim"]))
        elif pos is not None and not world.fog.is_explored(pos):
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
            if t.crate and t.crate in CRATE_SPECS:
                spec = CRATE_SPECS[t.crate]
                alarm = f" | alarme: ruído {spec.noise}" if spec.noise else ""
                lines.append((f"Caixa: {spec.name} ({world.loot_text(t.crate)}){alarm} - "
                              f"leve uma unidade até ela", spec.color))
            if t.building is not None:
                b = t.building
                lines.append((f"{b.name} HP {b.hp}/{b.max_hp}", COLORS[b.color_key]))
                if b.harvest and not b.hostile:
                    tiles = world.harvest_claims().get(b, [])
                    amount = world.harvest_yield(b.kind, len(tiles))
                    lines.append((f"Extrai {len(tiles)} tile(s) de {t_label(b.harvest)}: "
                                  f"+{amount} {RESOURCE_LABELS[b.harvest]}/turno "
                                  f"(máx. {b.stats.harvest_max})", COLORS["text_dim"]))
                if b.garrison:
                    guest = world.garrisoned(b)
                    lines.append((f"Abriga: {guest.name}" if guest else
                                  f"Vazia: mova uma unidade para cá (+{b.range_bonus} alcance, "
                                  f"+{b.vision_bonus} visão, protegida)", COLORS["text_dim"]))
            if t.unit is not None and t.unit is not ui.selected_unit:
                if isinstance(t.unit, Hero):
                    lines += self._hero_lines(world, t.unit)[:2]
                else:
                    lines.append((f"{t.unit.name} HP {t.unit.hp}/{t.unit.max_hp}", unit_color(t.unit)))
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
                if s.taunt_turns > 0 or s.rooted_turns > 0:
                    fx = []
                    if s.taunt_turns > 0 and s.taunt_hero:
                        fx.append(f"provocado por {HERO_SPECS[s.taunt_hero].name}")
                    if s.rooted_turns > 0:
                        fx.append("preso por raízes")
                    lines.append((", ".join(fx).capitalize(), COLORS["skill"]))
            level = world.noise_map.get(pos, 0)
            if level:
                lines.append((f"Ruído no último turno: {level}", COLORS["noise"]))
        if ui.skill:
            lines.append(("Roxo: alvos da habilidade. Clique para usar; Esc cancela.", COLORS["skill"]))
        elif ui.mode:
            lines.append(("Clique no mapa para aplicar. Botão direito/Esc cancela.", COLORS["text_dim"]))
        elif isinstance(ui.selected_unit, Hero) and not world.can_control(ui.selected_unit, ui.player_id):
            lines.append((f"Herói de P{ui.selected_unit.owner}: só o dono pode comandá-lo.",
                          COLORS["text_dim"]))
        elif ui.selected_unit is not None:
            lines.append(("Azul: mover | Vermelho: atacar | Amarelo: coletar | Verde: levantar caído",
                          COLORS["text_dim"]))
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
        help_text = "WASD: câmera | H: herói | Q/E/R: habilidades | M: música | Esc: menu"
        surface.blit(self.font(17).render(help_text, True, COLORS["text_dim"]),
                     (x, self.rect.bottom - 22))
