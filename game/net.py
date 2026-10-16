"""Transporte TCP do co-op: mensagens JSON (um objeto por linha) lidas em threads.

Sem dependência de pygame. Só trafega JSON (nunca pickle): cada mensagem recebida é um
`dict` validado depois pela camada de protocolo (`game/coop.py`).
"""
from __future__ import annotations

import json
import queue
import socket
import threading
from typing import Any, Optional

MAX_MESSAGE_BYTES = 4 * 1024 * 1024
SOCKET_TIMEOUT = 5.0

# eventos entregues por poll(): (peer_id, tipo, dado)
#   tipo "joined" -> dado = endereço; "msg" -> dado = dict; "closed" -> dado = None
Event = tuple[int, str, Any]


class NetError(Exception):
    """Falha de rede/protocolo com mensagem legível para o jogador."""


def parse_address(text: str, default_port: int) -> tuple[str, int]:
    text = text.strip()
    if not text:
        raise NetError("Informe o IP do anfitrião.")
    host, sep, port = text.rpartition(":")
    if not sep:
        return text, default_port
    if not host:
        raise NetError(f"Endereço inválido: {text!r}.")
    try:
        number = int(port)
    except ValueError:
        raise NetError(f"Porta inválida: {port!r}.") from None
    if not 0 < number < 65536:
        raise NetError(f"Porta fora do intervalo: {number}.")
    return host, number


def local_ip() -> str:
    """IP desta máquina na rede local (para informar aos amigos). Não envia pacotes."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def encode(msg: dict) -> bytes:
    return (json.dumps(msg, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


class Connection:
    """Um socket com thread de leitura; mensagens vão para a fila compartilhada `inbox`."""

    def __init__(self, sock: socket.socket, inbox: "queue.Queue[Event]", peer_id: int):
        self.sock = sock
        self.inbox = inbox
        self.peer_id = peer_id
        self.alive = True
        self._send_lock = threading.Lock()
        self._close_lock = threading.Lock()
        sock.settimeout(SOCKET_TIMEOUT)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        self._thread = threading.Thread(target=self._read_loop, daemon=True,
                                        name=f"net-reader-{peer_id}")

    def start(self) -> "Connection":
        self._thread.start()
        return self

    def send(self, msg: dict) -> bool:
        if not self.alive:
            return False
        data = encode(msg)
        try:
            with self._send_lock:
                self.sock.sendall(data)
            return True
        except OSError:
            self.close()
            return False

    def _read_loop(self) -> None:
        buf = b""
        try:
            while self.alive:
                try:
                    chunk = self.sock.recv(65536)
                except TimeoutError:
                    continue
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    msg = json.loads(line.decode("utf-8"))
                    if not isinstance(msg, dict):
                        raise ValueError("mensagem não é um objeto JSON")
                    self.inbox.put((self.peer_id, "msg", msg))
                if len(buf) > MAX_MESSAGE_BYTES:
                    raise ValueError("mensagem grande demais")
        except (OSError, ValueError):
            pass
        finally:
            self.close()
            self.inbox.put((self.peer_id, "closed", None))

    def close(self) -> None:
        with self._close_lock:
            if not self.alive:
                return
            self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


def _drain(inbox: "queue.Queue[Event]") -> list[Event]:
    events = []
    while True:
        try:
            events.append(inbox.get_nowait())
        except queue.Empty:
            return events


class HostTransport:
    """Servidor: aceita até `max_clients` conexões. O anfitrião é o jogador 1."""

    def __init__(self, port: int, max_clients: int, bind: str = ""):
        self.inbox: "queue.Queue[Event]" = queue.Queue()
        self.max_clients = max_clients
        self._clients: dict[int, Connection] = {}
        self._lock = threading.Lock()
        self._next_id = 2
        try:
            self._server = socket.create_server((bind, port))
        except OSError as exc:
            raise NetError(f"Não foi possível abrir a porta {port}: {exc.strerror or exc}") from exc
        self._server.settimeout(0.5)
        self.port = self._server.getsockname()[1]
        self._running = True
        threading.Thread(target=self._accept_loop, daemon=True, name="net-accept").start()

    def _accept_loop(self) -> None:
        while self._running:
            try:
                sock, addr = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with self._lock:
                full = len(self._clients) >= self.max_clients
                if not full:
                    pid = self._next_id
                    self._next_id += 1
                    conn = Connection(sock, self.inbox, pid)
                    self._clients[pid] = conn
            if full:
                try:
                    sock.sendall(encode({"t": "error", "reason": "Partida cheia."}))
                except OSError:
                    pass
                sock.close()
                continue
            self.inbox.put((pid, "joined", addr[0]))
            conn.start()

    def poll(self) -> list[Event]:
        events = _drain(self.inbox)
        for pid, kind, _ in events:
            if kind == "closed":
                with self._lock:
                    self._clients.pop(pid, None)
        return events

    def send(self, pid: int, msg: dict) -> None:
        with self._lock:
            conn = self._clients.get(pid)
        if conn is not None:
            conn.send(msg)

    def broadcast(self, msg: dict, to: Optional[set[int]] = None, exclude: Optional[int] = None) -> None:
        with self._lock:
            conns = [c for pid, c in self._clients.items()
                     if pid != exclude and (to is None or pid in to)]
        for conn in conns:
            conn.send(msg)

    def drop(self, pid: int) -> None:
        with self._lock:
            conn = self._clients.get(pid)
        if conn is not None:
            conn.close()

    def close(self) -> None:
        self._running = False
        try:
            self._server.close()
        except OSError:
            pass
        with self._lock:
            conns = list(self._clients.values())
        for conn in conns:
            conn.close()


class ClientTransport:
    def __init__(self, host: str, port: int, timeout: float = SOCKET_TIMEOUT):
        self.inbox: "queue.Queue[Event]" = queue.Queue()
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as exc:
            raise NetError(f"Não foi possível conectar a {host}:{port}: "
                           f"{exc.strerror or exc}") from exc
        self.conn = Connection(sock, self.inbox, 1).start()

    @property
    def alive(self) -> bool:
        return self.conn.alive

    def send(self, msg: dict) -> bool:
        return self.conn.send(msg)

    def poll(self) -> list[Event]:
        return _drain(self.inbox)

    def wait(self, timeout: float) -> Optional[Event]:
        try:
            return self.inbox.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self.conn.close()
