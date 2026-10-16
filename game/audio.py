"""Trilha sonora: toca em loop os arquivos de assets/audio/music via pygame.mixer.music."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pygame

from .config import MUSIC_DIR, MUSIC_EXTENSIONS, MUSIC_FADE_MS, MUSIC_VOLUME_DEFAULT


class MusicPlayer:
    """Playlist ordenada por nome; avança ao fim de cada faixa e recomeça do início.

    Falhas de áudio (sem dispositivo, arquivo corrompido) nunca derrubam o jogo:
    o player fica desabilitado e `error` descreve o motivo.
    """

    END_EVENT = pygame.USEREVENT + 1

    def __init__(self, folder: Path = MUSIC_DIR, volume: float = MUSIC_VOLUME_DEFAULT,
                 enabled: bool = True):
        self.folder = Path(folder)
        self.tracks: list[Path] = sorted(
            (p for p in self.folder.glob("*") if p.suffix.lower() in MUSIC_EXTENSIONS),
            key=lambda p: p.name.lower(),
        ) if self.folder.is_dir() else []
        self.index = 0
        self.volume = max(0.0, min(1.0, volume))
        self.enabled = enabled
        self.error: Optional[str] = None
        self.available = self._init_mixer()
        if not self.tracks and self.error is None:
            self.error = f"Nenhuma faixa em {self.folder}"

    def _init_mixer(self) -> bool:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.set_endevent(self.END_EVENT)
            return True
        except pygame.error as exc:
            self.error = f"Áudio indisponível: {exc}"
            return False

    @property
    def can_play(self) -> bool:
        return self.available and bool(self.tracks)

    @property
    def current_track(self) -> Optional[str]:
        return self.tracks[self.index].stem if self.tracks else None

    @property
    def playing(self) -> bool:
        return self.can_play and pygame.mixer.music.get_busy()

    def start(self) -> None:
        if self.enabled and self.can_play:
            self._play(self.index)

    def _play(self, index: int) -> None:
        # Tenta cada faixa uma vez; descarta silenciosamente as que não carregam.
        for _ in range(len(self.tracks)):
            self.index = index % len(self.tracks)
            try:
                pygame.mixer.music.load(str(self.tracks[self.index]))
                pygame.mixer.music.set_volume(self.volume)
                pygame.mixer.music.play(fade_ms=MUSIC_FADE_MS)
                self.error = None
                return
            except pygame.error as exc:
                self.error = f"Falha ao tocar {self.tracks[self.index].name}: {exc}"
                index = self.index + 1

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == self.END_EVENT and self.enabled and self.can_play:
            self._play(self.index + 1)

    def next_track(self) -> None:
        if self.enabled and self.can_play:
            self._play(self.index + 1)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not self.can_play:
            return
        if enabled:
            self._play(self.index)
        else:
            pygame.mixer.music.fadeout(MUSIC_FADE_MS // 2)

    def toggle(self) -> None:
        self.set_enabled(not self.enabled)

    def change_volume(self, delta: float) -> None:
        self.volume = round(max(0.0, min(1.0, self.volume + delta)), 2)
        if self.available:
            pygame.mixer.music.set_volume(self.volume)

    def stop(self) -> None:
        if self.available:
            pygame.mixer.music.stop()
