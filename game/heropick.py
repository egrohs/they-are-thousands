"""Tela de escolha de herói (início da partida / ao entrar no co-op)."""
from __future__ import annotations

from typing import Optional

import pygame

from .config import COLORS
from .renderer import player_color
from .stats import HERO_SKILLS, HERO_SPECS
from .world import World

CARD_W, CARD_H, GAP = 236, 330, 12


class HeroPicker:
    """Cartões com os heróis; papéis já escolhidos por outros jogadores ficam bloqueados
    (heróis sem dono — jogador que saiu — podem ser assumidos)."""

    def __init__(self, area: pygame.Rect):
        self.area = area
        self._fonts: dict[int, pygame.font.Font] = {}
        self.order = list(HERO_SPECS)
        n = len(self.order)
        cols = min(n, max(1, (area.w - 40 + GAP) // (CARD_W + GAP)))
        rows = (n + cols - 1) // cols
        total_w = cols * CARD_W + (cols - 1) * GAP
        total_h = rows * CARD_H + (rows - 1) * GAP
        x0 = area.centerx - total_w // 2
        y0 = max(area.top + 70, area.centery - total_h // 2 + 20)
        self.cards: list[tuple[str, pygame.Rect]] = []
        for i, hero_id in enumerate(self.order):
            r, c = divmod(i, cols)
            in_row = min(cols, n - r * cols)
            row_x = x0 + (cols - in_row) * (CARD_W + GAP) // 2
            self.cards.append((hero_id, pygame.Rect(row_x + c * (CARD_W + GAP),
                                                    y0 + r * (CARD_H + GAP), CARD_W, CARD_H)))

    def font(self, size: int) -> pygame.font.Font:
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(None, size)
        return self._fonts[size]

    def card_at(self, pos: tuple[int, int]) -> Optional[str]:
        return next((h for h, r in self.cards if r.collidepoint(pos)), None)

    def key_choice(self, key: int) -> Optional[str]:
        index = key - pygame.K_1
        return self.order[index] if 0 <= index < len(self.order) else None

    def _wrap(self, text: str, size: int, width: int) -> list[str]:
        font, words, lines, line = self.font(size), text.split(), [], ""
        for w in words:
            cand = f"{line} {w}".strip()
            if font.size(cand)[0] <= width:
                line = cand
            else:
                if line:
                    lines.append(line)
                line = w
        return lines + ([line] if line else [])

    def draw(self, surface: pygame.Surface, world: World, player_id: int,
             mouse: tuple[int, int]) -> None:
        shade = pygame.Surface(self.area.size, pygame.SRCALPHA)
        shade.fill((0, 0, 0, 185))
        surface.blit(shade, self.area.topleft)
        title = self.font(46).render("Escolha seu Herói", True, COLORS["title"])
        surface.blit(title, title.get_rect(midtop=(self.area.centerx, self.area.top + 18)))
        sub = (f"Você é P{player_id}. Cada jogador comanda um herói; ganham XP e sobem de nível. "
               "Teclas 1-5 ou clique.")
        img = self.font(22).render(sub, True, COLORS["text_dim"])
        surface.blit(img, img.get_rect(midtop=(self.area.centerx, self.area.top + 54)))
        for hero_id, rect in self.cards:
            self._draw_card(surface, world, player_id, hero_id, rect, rect.collidepoint(mouse))

    def _draw_card(self, surface, world: World, player_id: int, hero_id: str,
                   rect: pygame.Rect, hovered: bool) -> None:
        spec = HERO_SPECS[hero_id]
        ok, reason = world.can_pick_hero(hero_id, player_id)
        taken = world.hero(hero_id)
        bg = COLORS["button_hover"] if hovered and ok else COLORS["button"]
        if not ok:
            bg = COLORS["button_disabled"]
        pygame.draw.rect(surface, bg, rect, border_radius=8)
        pygame.draw.rect(surface, spec.color if ok else COLORS["hud_border"], rect, 2, border_radius=8)
        x, y, w = rect.x + 10, rect.y + 8, rect.w - 20
        index = self.order.index(hero_id) + 1
        head = self.font(28).render(f"[{index}] {spec.name}", True, spec.color)
        surface.blit(head, (x, y))
        y += head.get_height() + 2
        role = self.font(21).render(spec.role, True, COLORS["text"])
        surface.blit(role, (x, y))
        y += role.get_height() + 6
        stats = [f"HP {spec.hp}  Armadura {spec.armor}  Mov {spec.move}",
                 f"Alcance {spec.attack_range}  Dano {spec.damage}  Ruído {spec.noise}"]
        if spec.mana:
            stats.append(f"Mana {spec.mana} (+{spec.mana_regen}/turno)")
        for line in stats:
            img = self.font(19).render(line, True, COLORS["text_dim"])
            surface.blit(img, (x, y))
            y += img.get_height() + 1
        y += 4
        for skill in HERO_SKILLS[hero_id]:
            img = self.font(20).render(f"• {skill.name}", True, COLORS["skill"])
            surface.blit(img, (x, y))
            y += img.get_height()
            for part in self._wrap(skill.notes, 17, w - 10)[:2]:
                img = self.font(17).render(part, True, COLORS["text_dim"])
                surface.blit(img, (x + 10, y))
                y += img.get_height()
            y += 2
        if taken is not None:
            status = f"Com P{taken.owner}" if taken.owner else "Sem dono: clique para assumir"
            color = player_color(taken.owner) if taken.owner else COLORS["build_ok"]
        else:
            status, color = ("Disponível", COLORS["build_ok"]) if ok else (reason, COLORS["defeat"])
        img = self.font(20).render(status, True, color)
        surface.blit(img, img.get_rect(midbottom=(rect.centerx, rect.bottom - 8)))
