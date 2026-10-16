"""Co-op em rede (host/IP) em lockstep determinístico.

Todos os jogadores executam o mesmo `World` (mesma semente/mapa). As ações viram
*comandos* JSON; o anfitrião é a autoridade que os ordena: aplica cada comando e o
retransmite numerado para todos, que o aplicam na mesma ordem. Como as regras são
determinísticas (RNG com semente), os estados permanecem idênticos; um checksum do
estado é enviado pelo anfitrião e, se divergir, o cliente pede ressincronização
(recebe a partida do zero + histórico de comandos e reconstrói por replay).

Qualquer jogador pode fazer qualquer ação (construir, mover/atacar com qualquer unidade,
desfazer, encerrar turno, alternar névoa). Recursos, AP e visão são compartilhados.
Sem dependência de pygame.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Any, Optional

from .config import (DATA_DIR, NET_MAX_PLAYERS, NET_PORT, PHASE_DELAY)
from .grid import Pos
from .net import ClientTransport, HostTransport, NetError, parse_address
from .stats import BUILD_SPECS
from .turns import TurnManager
from .world import World

PROTOCOL_VERSION = 1
UNIT_OPS = ("move", "attack", "gather")
OPS = ("build", "repair", "undo", "end_turn", "fog", *UNIT_OPS)


def data_fingerprint() -> str:
    """Hash dos CSVs de balanceamento: todos precisam das mesmas regras para não divergir."""
    h = hashlib.sha1()
    for path in sorted(DATA_DIR.glob("*.csv")):
        h.update(path.name.encode())
        h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]


@dataclass(frozen=True)
class GameSetup:
    seed: int
    fog: bool
    map: Optional[dict] = None

    def to_json(self) -> dict:
        return {"seed": self.seed, "fog": self.fog, "map": self.map}

    @classmethod
    def from_json(cls, data: Any) -> "GameSetup":
        if not isinstance(data, dict):
            raise NetError("Configuração de partida inválida.")
        seed, fog, map_data = data.get("seed"), data.get("fog"), data.get("map")
        if type(seed) is not int or type(fog) is not bool:
            raise NetError("Configuração de partida inválida.")
        if map_data is not None and not isinstance(map_data, dict):
            raise NetError("Mapa da partida inválido.")
        return cls(seed, fog, map_data)

    @classmethod
    def new(cls, seed: Optional[int], fog: bool, map_data: Optional[dict]) -> "GameSetup":
        return cls(seed if seed is not None else random.randrange(1_000_000), fog, map_data)


# ======================================================================
# Comandos
# ======================================================================
def _pos(value: Any, world: World) -> Optional[Pos]:
    if (isinstance(value, (list, tuple)) and len(value) == 2
            and all(type(v) is int for v in value)):
        pos = (value[0], value[1])
        if world.grid.in_bounds(pos):
            return pos
    return None


def validate_command(cmd: Any, world: World) -> Optional[dict]:
    """Normaliza um comando recebido da rede; None se estiver malformado."""
    if not isinstance(cmd, dict) or cmd.get("op") not in OPS:
        return None
    op = cmd["op"]
    if op in ("undo", "end_turn"):
        return {"op": op}
    if op == "fog":
        enabled = cmd.get("enabled")
        return {"op": op, "enabled": enabled} if type(enabled) is bool else None
    if op == "build":
        pos, kind = _pos(cmd.get("pos"), world), cmd.get("kind")
        if pos is None or not isinstance(kind, str) or kind not in BUILD_SPECS:
            return None
        return {"op": op, "kind": kind, "pos": list(pos)}
    if op == "repair":
        pos = _pos(cmd.get("pos"), world)
        return None if pos is None else {"op": op, "pos": list(pos)}
    src, dst = _pos(cmd.get("from"), world), _pos(cmd.get("to"), world)
    if src is None or dst is None:
        return None
    return {"op": op, "from": list(src), "to": list(dst)}


def apply_command(world: World, turns: TurnManager, cmd: dict) -> bool:
    """Executa um comando já validado. Fases inimigas em andamento são resolvidas antes,
    para que todos apliquem o comando sobre o mesmo estado."""
    if turns.busy:
        turns.resolve_instantly()
    op = cmd["op"]
    if op == "fog":
        world.fog.enabled = cmd["enabled"]
        world.update_fog()
        return True
    if not turns.is_player_phase:
        return False
    if op == "end_turn":
        return turns.end_player_turn()
    if op == "undo":
        return world.undo()
    if op == "build":
        return world.build(cmd["kind"], tuple(cmd["pos"]))
    if op == "repair":
        return world.repair(tuple(cmd["pos"]))
    src, dst = tuple(cmd["from"]), tuple(cmd["to"])
    unit = world.grid.tile(src).unit
    if unit is None:
        world.message(f"Nenhuma unidade em {src}.")
        return False
    if op == "move":
        return world.move_unit(unit, dst)
    if op == "attack":
        return world.unit_attack(unit, dst)
    return world.unit_gather(unit, dst)


def world_checksum(world: World) -> str:
    """Resumo do estado de jogo (ignora log/efeitos visuais) para detectar divergência."""
    parts: list[Any] = [
        world.turn, world.ap, sorted(world.resources.items()), world.game_over, world.victory,
        world.zombies_killed, world.crates_found, world.final_horde_spawned, world.fog.enabled,
        len(world.history), world.rng.getstate(), len(world.pending_noise),
        sorted(world.fog.explored),
    ]
    for t in world.grid:
        b, u, s = t.building, t.unit, t.swarm
        parts.append((
            t.terrain.name, t.resource_amount, t.crate,
            (type(b).__name__, b.hp) if b else None,
            (type(u).__name__, u.hp, u.moved, u.acted) if u else None,
            (s.kind, s.count, s.wounds, s.aggressive, s.noise_target) if s else None,
        ))
    return hashlib.sha1(repr(parts).encode()).hexdigest()[:16]


# ======================================================================
# Sessões
# ======================================================================
class Session:
    """Partida local (sem rede). Base das sessões em rede: toda ação passa por `submit`
    e fica no `log` de comandos, permitindo hospedar a partida em andamento."""

    role = "local"

    def __init__(self, setup: GameSetup, phase_delay: float = PHASE_DELAY):
        self.phase_delay = phase_delay
        self.player_id = 1
        self.peer_cursors: dict[int, Pos] = {}
        self.generation = 0          # muda a cada partida (re)construída: a UI deve se resetar
        self.new_game_started = True  # a última reconstrução foi uma partida nova (reset de câmera)
        self.start(setup)

    # --- partida -----------------------------------------------------------
    def start(self, setup: GameSetup, log: Optional[list[dict]] = None, new_game: bool = True) -> None:
        self.setup = setup
        self.world = World(setup.seed, fog_enabled=setup.fog, map_data=setup.map)
        self.turns = TurnManager(self.world, phase_delay=self.phase_delay)
        self.log: list[dict] = []
        for cmd in log or []:
            valid = validate_command(cmd, self.world)
            if valid is None:
                raise NetError("Histórico de comandos inválido.")
            apply_command(self.world, self.turns, valid)
            self.log.append(valid)
        self.turns.resolve_instantly()
        self.generation += 1
        self.new_game_started = new_game

    def adopt(self, other: "Session") -> "Session":
        """Assume a partida de outra sessão (ex.: hospedar o jogo atual / sair do co-op)."""
        self.setup, self.world, self.turns, self.log = other.setup, other.world, other.turns, other.log
        self.generation = other.generation + 1
        self.new_game_started = False
        return self

    @classmethod
    def detached(cls, other: "Session") -> "Session":
        """Sessão local que continua a partida de `other` (ex.: ao sair/perder o co-op)."""
        session = cls.__new__(cls)
        session.phase_delay = other.phase_delay
        session.player_id = 1
        session.peer_cursors = {}
        return session.adopt(other)

    def new_game(self, setup: GameSetup) -> bool:
        self.start(setup)
        return True

    @property
    def can_restart(self) -> bool:
        return True

    # --- ações ---------------------------------------------------------------
    def submit(self, cmd: dict) -> None:
        valid = validate_command(cmd, self.world)
        if valid is not None:
            apply_command(self.world, self.turns, valid)
            self.log.append(valid)

    def update(self, dt: float) -> None:
        self.turns.update(dt)

    def send_cursor(self, pos: Optional[Pos]) -> None:
        pass

    # --- informação ------------------------------------------------------------
    @property
    def online(self) -> bool:
        return False

    @property
    def connected(self) -> bool:
        return True

    @property
    def player_ids(self) -> list[int]:
        return [1]

    @property
    def status(self) -> str:
        return ""

    def close(self) -> None:
        pass


def _cursor(value: Any, world: World) -> Optional[Pos]:
    return _pos(value, world)


class HostSession(Session):
    role = "host"

    def __init__(self, setup: GameSetup, port: int = NET_PORT,
                 phase_delay: float = PHASE_DELAY, bind: str = "",
                 adopt: Optional[Session] = None):
        self.transport = HostTransport(port, NET_MAX_PLAYERS - 1, bind)
        self.port = self.transport.port
        self.players: dict[int, str] = {}   # id -> endereço (só após o "hello" aceito)
        self.seq = 0
        self._last_cursor: Optional[Pos] = None
        super().__init__(setup, phase_delay)
        if adopt is not None:
            self.adopt(adopt)
            self.seq = len(self.log)
        self.world.message(f"Co-op: hospedando na porta {self.port}.")

    def start(self, setup: GameSetup, log: Optional[list[dict]] = None, new_game: bool = True) -> None:
        super().start(setup, log, new_game)
        self.seq = len(self.log)
        if getattr(self, "players", None):
            self.transport.broadcast({"t": "start", "setup": setup.to_json()}, to=set(self.players))
            self._send_check()

    # --- execução ---------------------------------------------------------------
    def submit(self, cmd: dict) -> None:
        self._execute(cmd, 1)

    def _execute(self, cmd: Any, by: int) -> None:
        valid = validate_command(cmd, self.world)
        if valid is None:
            return
        if self.turns.busy:
            self.turns.resolve_instantly()
            self._send_check()
        apply_command(self.world, self.turns, valid)
        self.log.append(valid)
        self.seq += 1
        self.transport.broadcast({"t": "cmd", "seq": self.seq, "by": by, "cmd": valid},
                                 to=set(self.players))
        if not self.turns.busy:
            self._send_check()

    def _send_check(self) -> None:
        if self.players:
            self.transport.broadcast({"t": "check", "seq": self.seq,
                                      "sum": world_checksum(self.world)}, to=set(self.players))

    def _welcome(self, pid: int) -> None:
        self.transport.send(pid, {"t": "welcome", "id": pid, "setup": self.setup.to_json(),
                                  "log": self.log, "seq": self.seq,
                                  "players": self.player_ids,
                                  "cursors": {str(k): list(v) for k, v in self.peer_cursors.items()}})
        if not self.turns.busy:
            self.transport.send(pid, {"t": "check", "seq": self.seq, "sum": world_checksum(self.world)})

    def _broadcast_players(self) -> None:
        self.transport.broadcast({"t": "players", "ids": self.player_ids}, to=set(self.players))

    # --- rede -------------------------------------------------------------------
    def update(self, dt: float) -> None:
        was_busy = self.turns.busy
        self.turns.update(dt)
        if was_busy and not self.turns.busy:
            self._send_check()
        for pid, kind, data in self.transport.poll():
            if kind == "closed":
                if self.players.pop(pid, None) is not None:
                    self.peer_cursors.pop(pid, None)
                    self.world.message(f"Co-op: P{pid} saiu da partida.")
                    self._broadcast_players()
                    self.transport.broadcast({"t": "cursor", "id": pid, "pos": None},
                                             to=set(self.players))
            elif kind == "msg":
                self._handle(pid, data)

    def _handle(self, pid: int, msg: dict) -> None:
        t = msg.get("t")
        if pid not in self.players:
            if t != "hello":
                return
            if msg.get("version") != PROTOCOL_VERSION or msg.get("data") != data_fingerprint():
                self.transport.send(pid, {"t": "error", "reason": "Versão do jogo ou dados de "
                                          "balanceamento (data/*.csv) diferentes do anfitrião."})
                self.transport.drop(pid)
                return
            self.players[pid] = str(msg.get("addr", "?"))
            self._welcome(pid)
            self._broadcast_players()
            self.world.message(f"Co-op: P{pid} entrou na partida.")
            return
        if t == "cmd":
            self._execute(msg.get("cmd"), pid)
        elif t == "cursor":
            pos = _cursor(msg.get("pos"), self.world)
            if pos is None:
                self.peer_cursors.pop(pid, None)
            else:
                self.peer_cursors[pid] = pos
            self.transport.broadcast({"t": "cursor", "id": pid, "pos": list(pos) if pos else None},
                                     to=set(self.players), exclude=pid)
        elif t == "resync":
            self._welcome(pid)

    def send_cursor(self, pos: Optional[Pos]) -> None:
        if pos != self._last_cursor:
            self._last_cursor = pos
            self.transport.broadcast({"t": "cursor", "id": 1, "pos": list(pos) if pos else None},
                                     to=set(self.players))

    @property
    def online(self) -> bool:
        return True

    @property
    def player_ids(self) -> list[int]:
        return [1, *sorted(self.players)]

    @property
    def status(self) -> str:
        return f"Co-op HOST · {len(self.player_ids)}J"

    def close(self) -> None:
        self.transport.close()


class ClientSession(Session):
    role = "client"

    def __init__(self, address: str, phase_delay: float = PHASE_DELAY,
                 timeout: float = 5.0):
        self.host, self.port = parse_address(address, NET_PORT)
        self.transport = ClientTransport(self.host, self.port, timeout)
        self.applied = 0
        self.pending_checks: dict[int, str] = {}
        self.desyncs = 0
        self._ids: list[int] = []
        self._last_cursor: Optional[Pos] = None
        self._awaiting_resync = False
        self.phase_delay = phase_delay
        self.peer_cursors = {}
        self.generation = 0
        self.new_game_started = True
        self.transport.send({"t": "hello", "version": PROTOCOL_VERSION, "data": data_fingerprint()})
        welcome = self._wait_welcome(timeout)
        try:
            self._load(welcome)
        except NetError:
            self.transport.close()
            raise
        self.world.message(f"Co-op: conectado a {self.host}:{self.port} como P{self.player_id}.")

    def _wait_welcome(self, timeout: float) -> dict:
        while True:
            event = self.transport.wait(timeout)
            if event is None:
                self.transport.close()
                raise NetError("O anfitrião não respondeu.")
            _, kind, msg = event
            if kind == "closed":
                raise NetError("Conexão recusada pelo anfitrião.")
            if msg.get("t") == "error":
                self.transport.close()
                raise NetError(str(msg.get("reason", "Erro do anfitrião.")))
            if msg.get("t") == "welcome":
                return msg

    def _load(self, msg: dict, new_game: bool = True) -> None:
        pid, seq, log = msg.get("id"), msg.get("seq"), msg.get("log")
        if type(pid) is not int or type(seq) is not int or not isinstance(log, list) or seq != len(log):
            raise NetError("Resposta do anfitrião inválida.")
        self.player_id = pid
        self.start(GameSetup.from_json(msg.get("setup")), log, new_game)
        self.applied = seq
        self.pending_checks.clear()
        self._awaiting_resync = False
        self._set_players(msg.get("players"))
        self.peer_cursors = {}
        cursors = msg.get("cursors")
        if isinstance(cursors, dict):
            for key, value in cursors.items():
                pos = _cursor(value, self.world)
                if key.isdigit() and pos is not None and int(key) != self.player_id:
                    self.peer_cursors[int(key)] = pos

    def _set_players(self, ids: Any) -> None:
        if isinstance(ids, list) and all(type(i) is int for i in ids):
            self._ids = sorted(ids)

    # --- ações: vão para o anfitrião, que as devolve numeradas a todos -------------
    def submit(self, cmd: dict) -> None:
        valid = validate_command(cmd, self.world)
        if valid is not None and self.connected:
            self.transport.send({"t": "cmd", "cmd": valid})

    def new_game(self, setup: GameSetup) -> bool:
        return False

    @property
    def can_restart(self) -> bool:
        return False

    def send_cursor(self, pos: Optional[Pos]) -> None:
        if pos != self._last_cursor and self.connected:
            self._last_cursor = pos
            self.transport.send({"t": "cursor", "pos": list(pos) if pos else None})

    # --- rede -------------------------------------------------------------------
    def update(self, dt: float) -> None:
        self.turns.update(dt)
        for _, kind, msg in self.transport.poll():
            if kind == "closed":
                self.world.message("Co-op: conexão com o anfitrião perdida. Continuando offline.")
                continue
            try:
                self._handle(msg)
            except NetError as exc:
                self.world.message(f"Co-op: {exc}")
                self._request_resync()
        self._compare_checks()

    def _handle(self, msg: dict) -> None:
        t = msg.get("t")
        if t == "cmd":
            if self._awaiting_resync:
                return
            seq = msg.get("seq")
            valid = validate_command(msg.get("cmd"), self.world)
            if seq != self.applied + 1 or valid is None:
                raise NetError("comando fora de ordem.")
            if self.turns.busy:
                self.turns.resolve_instantly()
            self._compare_checks()
            apply_command(self.world, self.turns, valid)
            self.log.append(valid)
            self.applied = seq
        elif t == "check":
            seq, value = msg.get("seq"), msg.get("sum")
            if type(seq) is int and isinstance(value, str) and not self._awaiting_resync:
                self.pending_checks[seq] = value
        elif t == "welcome":
            self._load(msg, new_game=False)
            self.world.message("Co-op: partida ressincronizada com o anfitrião.")
        elif t == "start":
            self._load({"id": self.player_id, "setup": msg.get("setup"), "log": [], "seq": 0,
                        "players": self._ids})
            self.world.message("Co-op: o anfitrião iniciou uma nova partida.")
        elif t == "players":
            self._set_players(msg.get("ids"))
            for pid in list(self.peer_cursors):
                if pid not in self._ids:
                    del self.peer_cursors[pid]
        elif t == "cursor":
            pid, pos = msg.get("id"), _cursor(msg.get("pos"), self.world)
            if type(pid) is int and pid != self.player_id:
                if pos is None:
                    self.peer_cursors.pop(pid, None)
                else:
                    self.peer_cursors[pid] = pos
        elif t == "error":
            self.world.message(f"Co-op: {msg.get('reason', 'erro do anfitrião')}")

    def _compare_checks(self) -> None:
        if self.turns.busy or not self.pending_checks:
            return
        for seq in sorted(self.pending_checks):
            if seq > self.applied:
                break
            value = self.pending_checks.pop(seq)
            if seq == self.applied and value != world_checksum(self.world):
                self.desyncs += 1
                self.world.message("Co-op: estado divergiu do anfitrião, ressincronizando...")
                self._request_resync()
                return

    def _request_resync(self) -> None:
        if not self._awaiting_resync and self.connected:
            self._awaiting_resync = True
            self.pending_checks.clear()
            self.transport.send({"t": "resync"})

    @property
    def online(self) -> bool:
        return True

    @property
    def connected(self) -> bool:
        return self.transport.alive

    @property
    def player_ids(self) -> list[int]:
        return self._ids or [1, self.player_id]

    @property
    def status(self) -> str:
        if not self.connected:
            return "Co-op: desconectado"
        return f"Co-op P{self.player_id} · {len(self.player_ids)}J"

    def close(self) -> None:
        self.transport.close()
