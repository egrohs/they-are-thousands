"""Máquina de estados das fases do turno."""
from __future__ import annotations

from enum import Enum
from typing import Callable

from .config import PHASE_DELAY
from .world import World


class Phase(Enum):
    PLAYER = "Fase do Jogador"
    NOISE = "Propagação de Som"
    ZOMBIE_MOVE = "Movimento dos Zumbis"
    DEFENSE = "Defesas Automáticas"
    ZOMBIE_ATTACK = "Ataque dos Zumbis"
    INFECTION = "Infecção"
    CLEANUP = "Fim de Rodada"
    GAME_OVER = "Fim de Jogo"


ENEMY_SEQUENCE: tuple[Phase, ...] = (
    Phase.NOISE,
    Phase.ZOMBIE_MOVE,
    Phase.DEFENSE,
    Phase.ZOMBIE_ATTACK,
    Phase.INFECTION,
    Phase.CLEANUP,
)


class TurnManager:
    """Player -> Som -> Zumbis (mover/defesa/ataque) -> Infecção -> Cleanup -> Player.

    Cada fase automática é executada ao entrar e permanece visível por `phase_delay`
    segundos, permitindo ao jogador acompanhar a resolução.
    """

    def __init__(self, world: World, phase_delay: float = PHASE_DELAY):
        self.world = world
        self.phase_delay = phase_delay
        self.phase = Phase.GAME_OVER if world.game_over else Phase.PLAYER
        self._queue: list[Phase] = []
        self._timer = 0.0
        self._handlers: dict[Phase, Callable[[], None]] = {
            Phase.NOISE: world.propagate_noise,
            Phase.ZOMBIE_MOVE: world.zombies_move,
            Phase.DEFENSE: world.ballistas_fire,
            Phase.ZOMBIE_ATTACK: world.zombies_attack,
            Phase.INFECTION: world.resolve_infection,
            Phase.CLEANUP: world.end_round,
        }

    @property
    def is_player_phase(self) -> bool:
        return self.phase is Phase.PLAYER

    @property
    def busy(self) -> bool:
        return self.phase not in (Phase.PLAYER, Phase.GAME_OVER)

    def end_player_turn(self) -> bool:
        if not self.is_player_phase or self.world.game_over:
            return False
        self.world.message("Turno encerrado pelo jogador.")
        self._queue = list(ENEMY_SEQUENCE)
        self._advance()
        return True

    def _advance(self) -> None:
        if self.world.game_over:
            self.phase = Phase.GAME_OVER
            self._queue.clear()
            return
        if not self._queue:
            self.phase = Phase.PLAYER
            self.world.begin_player_phase()
            return
        self.phase = self._queue.pop(0)
        self._handlers[self.phase]()
        self.world.check_defeat()
        self._timer = self.phase_delay

    def update(self, dt: float) -> None:
        if not self.busy:
            return
        self._timer -= dt
        if self._timer <= 0:
            self._advance()

    def resolve_instantly(self) -> None:
        while self.busy:
            self._advance()
