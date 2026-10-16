"""Carregamento e cache de sprites a partir de assets/images.

As imagens são retratos com fundo opaco; são recortadas em modo "cover" para caber
no tile (quadrado), ancoradas na parte superior para privilegiar cabeça/tronco.
Qualquer imagem ausente ou inválida retorna None e o renderer usa o placeholder.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pygame

from .config import IMAGES_DIR, SPRITE_FILES

Color = tuple[int, int, int]

MAX_CACHE = 400


class SpriteManager:
    def __init__(self, folder: Path = IMAGES_DIR, files: dict[str, tuple[str, float]] = SPRITE_FILES):
        self.folder = Path(folder)
        self.files = files
        self._sources: dict[str, Optional[pygame.Surface]] = {}
        self._cache: dict[tuple, pygame.Surface] = {}
        self.errors: list[str] = []

    def has(self, key: str) -> bool:
        return self._source(key) is not None

    def _source(self, key: str) -> Optional[pygame.Surface]:
        if key not in self._sources:
            self._sources[key] = None
            entry = self.files.get(key)
            if entry is not None:
                path = self.folder / entry[0]
                try:
                    img = pygame.image.load(str(path))
                    if pygame.display.get_surface() is not None:
                        img = img.convert_alpha()
                    self._sources[key] = img
                except (pygame.error, FileNotFoundError) as exc:
                    self.errors.append(f"{path.name}: {exc}")
        return self._sources[key]

    def get(self, key: str, size: int, tint: Optional[Color] = None) -> Optional[pygame.Surface]:
        """Sprite quadrado `size`×`size`; `tint` multiplica as cores (ex.: escurecer/infectar)."""
        size = max(1, int(size))
        cache_key = (key, size, tint)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        src = self._source(key)
        if src is None:
            return None
        anchor = self.files[key][1]
        w, h = src.get_size()
        scale = size / min(w, h)
        sw, sh = max(size, round(w * scale)), max(size, round(h * scale))
        scaled = pygame.transform.smoothscale(src, (sw, sh))
        x = (sw - size) // 2
        y = round((sh - size) * anchor)
        sprite = scaled.subsurface(pygame.Rect(x, y, size, size)).copy()
        if tint is not None:
            sprite.fill((*tint, 255), special_flags=pygame.BLEND_RGBA_MULT)
        if len(self._cache) >= MAX_CACHE:
            self._cache.clear()
        self._cache[cache_key] = sprite
        return sprite
