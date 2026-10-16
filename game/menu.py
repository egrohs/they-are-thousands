"""Menu inicial / de pausa com opções de partida (ex.: névoa de guerra)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pygame

from .config import COLORS


@dataclass
class Settings:
    fog_enabled: bool = True
    music_enabled: bool = True
    music_volume: float = 0.5
    music_available: bool = True


@dataclass
class MenuItem:
    action: str
    label: str
    rect: pygame.Rect


class Menu:
    """Retorna ações: 'resume', 'new_game', 'toggle_fog', 'toggle_music',
    'volume_up', 'volume_down', 'quit'."""

    ITEM_W = 380
    ITEM_H = 44
    GAP = 10

    def __init__(self, screen_rect: pygame.Rect):
        self.screen_rect = screen_rect
        self.open = True
        self.started = False  # False = menu inicial; True = pausa durante a partida
        self._fonts: dict[int, pygame.font.Font] = {}
        self.items: list[MenuItem] = []
        self.focus = 0

    def font(self, size: int) -> pygame.font.Font:
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(None, size)
        return self._fonts[size]

    def layout(self, settings: Settings) -> list[MenuItem]:
        fog = "LIGADA" if settings.fog_enabled else "DESLIGADA"
        if settings.music_available:
            music = "LIGADA" if settings.music_enabled else "DESLIGADA"
        else:
            music = "INDISPONÍVEL"
        entries = [
            ("resume", "Continuar" if self.started else "Iniciar Jogo"),
            ("new_game", "Novo Mapa"),
            ("toggle_fog", f"Névoa de Guerra: {fog}  [F]"),
            ("toggle_music", f"Música: {music}  [M]"),
            ("volume", f"Volume: {round(settings.music_volume * 100)}%  [< / >]"),
            ("quit", "Sair"),
        ]
        total = len(entries) * (self.ITEM_H + self.GAP) - self.GAP
        top = self.screen_rect.centery - total // 2 + 40
        x = self.screen_rect.centerx - self.ITEM_W // 2
        self.items = [MenuItem(a, label, pygame.Rect(x, top + i * (self.ITEM_H + self.GAP),
                                                     self.ITEM_W, self.ITEM_H))
                      for i, (a, label) in enumerate(entries)]
        self.focus %= len(self.items)
        return self.items

    def handle_event(self, event: pygame.event.Event, settings: Settings) -> Optional[str]:
        items = self.layout(settings)
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_w):
                self.focus = (self.focus - 1) % len(items)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.focus = (self.focus + 1) % len(items)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                action = items[self.focus].action
                return "volume_up" if action == "volume" else action
            elif event.key in (pygame.K_LEFT, pygame.K_a, pygame.K_MINUS, pygame.K_KP_MINUS):
                return "volume_down"
            elif event.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_EQUALS, pygame.K_PLUS,
                               pygame.K_KP_PLUS):
                return "volume_up"
            elif event.key == pygame.K_ESCAPE:
                return "resume"
            elif event.key == pygame.K_f:
                return "toggle_fog"
            elif event.key == pygame.K_m:
                return "toggle_music"
        elif event.type == pygame.MOUSEMOTION:
            for i, item in enumerate(items):
                if item.rect.collidepoint(event.pos):
                    self.focus = i
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
            for item in items:
                if item.rect.collidepoint(event.pos):
                    if item.action == "volume":
                        left_half = event.pos[0] < item.rect.centerx
                        return "volume_down" if left_half or event.button == 3 else "volume_up"
                    if event.button == 1:
                        return item.action
        return None

    def draw(self, surface: pygame.Surface, settings: Settings,
             now_playing: Optional[str] = None) -> None:
        shade = pygame.Surface(self.screen_rect.size, pygame.SRCALPHA)
        shade.fill((*COLORS["menu_bg"], 215))
        surface.blit(shade, self.screen_rect.topleft)
        items = self.layout(settings)
        cx = self.screen_rect.centerx
        title = self.font(72).render("THEY ARE THOUSANDS", True, COLORS["title"])
        surface.blit(title, title.get_rect(center=(cx, items[0].rect.top - 110)))
        sub = "Pausado" if self.started else "Sobreviva 15 turnos à horda"
        img = self.font(28).render(sub, True, COLORS["text_dim"])
        surface.blit(img, img.get_rect(center=(cx, items[0].rect.top - 60)))
        for i, item in enumerate(items):
            color = COLORS["button_hover"] if i == self.focus else COLORS["button"]
            if item.action == "toggle_fog" and settings.fog_enabled:
                color = COLORS["button_active"]
            if item.action == "toggle_music" and settings.music_enabled and settings.music_available:
                color = COLORS["button_active"]
            if item.action == "volume":
                bar = item.rect.inflate(-16, 0)
                bar.h, bar.bottom = 4, item.rect.bottom - 5
                pygame.draw.rect(surface, color, item.rect, border_radius=8)
                pygame.draw.rect(surface, COLORS["hud_border"], bar)
                bar.w = round(bar.w * settings.music_volume)
                pygame.draw.rect(surface, COLORS["ap"], bar)
            else:
                pygame.draw.rect(surface, color, item.rect, border_radius=8)
            border = COLORS["select"] if i == self.focus else COLORS["hud_border"]
            pygame.draw.rect(surface, border, item.rect, 2, border_radius=8)
            label = self.font(30).render(item.label, True, COLORS["text"])
            surface.blit(label, label.get_rect(center=item.rect.center))
        hint = ("Névoa: inexplorado fica preto; áreas exploradas fora da visão escondem os "
                "zumbis. Pode ser alterada a qualquer momento.")
        img = self.font(20).render(hint, True, COLORS["text_dim"])
        surface.blit(img, img.get_rect(center=(cx, items[-1].rect.bottom + 30)))
        if now_playing:
            img = self.font(22).render(f"Tocando: {now_playing}", True, COLORS["text_dim"])
            surface.blit(img, img.get_rect(center=(cx, items[-1].rect.bottom + 56)))
