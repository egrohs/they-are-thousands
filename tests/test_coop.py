import os
import random
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from game.coop import (ClientSession, GameSetup, HostSession, Session, apply_command,
                       data_fingerprint, validate_command, world_checksum)
from game.net import NetError, parse_address

ROOT = Path(__file__).resolve().parent.parent


def bot_turn(session: Session, rng: random.Random) -> None:
    """Joga um turno com ações variadas (inclui desfazer) via comandos."""
    world = session.world
    for unit in sorted(world.grid.units(), key=lambda u: u.pos):
        if session.world is not world or not unit.alive:
            continue
        targets = sorted(world.attack_targets(unit))
        if targets:
            session.submit({"op": "attack", "from": list(unit.pos), "to": list(targets[0])})
            continue
        moves = sorted(world.unit_moves(unit))
        if moves:
            session.submit({"op": "move", "from": list(unit.pos), "to": list(rng.choice(moves))})
    zone = sorted(world.build_zone())
    for kind in ("wall", "tent", "ballista"):
        session.submit({"op": "build", "kind": kind, "pos": list(rng.choice(zone))})
    if rng.random() < 0.3:
        session.submit({"op": "undo"})
    session.submit({"op": "end_turn"})
    session.turns.resolve_instantly()


def play(seed: int, turns: int, fog: bool = True) -> Session:
    session = Session(GameSetup(seed, fog), phase_delay=0)
    rng = random.Random(seed)
    for _ in range(turns):
        if session.world.game_over:
            break
        bot_turn(session, rng)
    return session


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.session = Session(GameSetup(5, True), phase_delay=0)
        self.world = self.session.world

    def test_validation_rejects_garbage(self):
        bad = [None, 3, "x", {}, {"op": "nuke"}, {"op": "build", "kind": "wall"},
               {"op": "build", "kind": "castle", "pos": [1, 1]},
               {"op": "build", "kind": "wall", "pos": [1, 99]},
               {"op": "build", "kind": "wall", "pos": [1.0, 2]},
               {"op": "build", "kind": "wall", "pos": [True, 2]},
               {"op": "move", "from": [1, 1]}, {"op": "fog", "enabled": "yes"},
               {"op": "repair", "pos": "1,1"}]
        for cmd in bad:
            self.assertIsNone(validate_command(cmd, self.world), cmd)

    def test_validation_normalizes(self):
        self.assertEqual(validate_command({"op": "undo", "extra": 1}, self.world), {"op": "undo"})
        self.assertEqual(validate_command({"op": "move", "from": (1, 2), "to": [3, 4]}, self.world),
                         {"op": "move", "from": [1, 2], "to": [3, 4]})

    def test_fog_is_a_shared_command(self):
        self.session.submit({"op": "fog", "enabled": False})
        self.assertFalse(self.world.fog.enabled)
        self.assertEqual(self.session.log[-1], {"op": "fog", "enabled": False})

    def test_command_during_enemy_phase_resolves_it_first(self):
        self.session.submit({"op": "end_turn"})
        self.assertTrue(self.session.turns.busy)
        turn = self.world.turn
        apply_command(self.world, self.session.turns, {"op": "undo"})
        self.assertFalse(self.session.turns.busy)
        self.assertEqual(self.world.turn, turn + 1)

    def test_missing_unit_is_rejected(self):
        empty = next(t.pos for t in self.world.grid if t.unit is None)
        cmd = {"op": "move", "from": list(empty), "to": [0, 0]}
        self.assertFalse(apply_command(self.world, self.session.turns, cmd))

    def test_parse_address(self):
        self.assertEqual(parse_address("10.0.0.2", 5757), ("10.0.0.2", 5757))
        self.assertEqual(parse_address(" 10.0.0.2:6000 ", 5757), ("10.0.0.2", 6000))
        for bad in ("", ":80", "1.2.3.4:x", "1.2.3.4:70000"):
            with self.assertRaises(NetError):
                parse_address(bad, 5757)


class DeterminismTests(unittest.TestCase):
    def test_replaying_the_log_rebuilds_the_same_state(self):
        session = play(seed=21, turns=8)
        self.assertGreater(len(session.log), 20)
        replay = Session(session.setup, phase_delay=0)
        replay.start(session.setup, session.log)
        self.assertEqual(world_checksum(replay.world), world_checksum(session.world))

    def test_same_result_across_processes_with_different_hash_seeds(self):
        code = ("from game.coop import world_checksum; from tests.test_coop import play; "
                "print(world_checksum(play(seed=33, turns=10).world))")
        sums = set()
        for hash_seed in ("1", "987"):
            env = dict(os.environ, PYTHONHASHSEED=hash_seed, SDL_VIDEODRIVER="dummy",
                       SDL_AUDIODRIVER="dummy")
            out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                                 capture_output=True, text=True, timeout=120)
            self.assertEqual(out.returncode, 0, out.stderr)
            sums.add(out.stdout.strip().splitlines()[-1])
        self.assertEqual(len(sums), 1, sums)


def pump(sessions, until, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for s in sessions:
            s.update(0.0)
        if until():
            return True
        time.sleep(0.005)
    return False


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.host = HostSession(GameSetup(9, True), port=0, phase_delay=0, bind="127.0.0.1")
        self.addr = f"127.0.0.1:{self.host.port}"
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.host.close()

    def connect(self) -> ClientSession:
        stop = threading.Event()

        def serve():
            while not stop.is_set():
                self.host.update(0.0)
                time.sleep(0.005)
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            client = ClientSession(self.addr, phase_delay=0, timeout=5)
        finally:
            stop.set()
            thread.join()
        self.clients.append(client)
        return client

    def synced(self, client) -> bool:
        return (client.applied == self.host.seq and not client.turns.busy
                and world_checksum(client.world) == world_checksum(self.host.world))

    def test_shared_actions_resources_and_turns(self):
        self.host.submit({"op": "fog", "enabled": False})  # sem névoa nada trava o desfazer
        a = self.connect()
        self.assertEqual(a.player_id, 2)
        self.assertEqual(world_checksum(a.world), world_checksum(self.host.world))
        everyone = [self.host, a]
        zone = sorted(self.host.world.build_zone())
        free = [p for p in zone if self.host.world.can_build("wall", p)[0]]
        wood = self.host.world.resources["wood"]
        # o cliente constrói; o anfitrião vê e gasta dos mesmos recursos
        a.submit({"op": "build", "kind": "wall", "pos": list(free[0])})
        self.assertTrue(pump(everyone, lambda: self.host.world.grid.tile(free[0]).building is not None))
        self.assertTrue(pump(everyone, lambda: self.synced(a)))
        self.assertLess(a.world.resources["wood"], wood)
        self.host.submit({"op": "build", "kind": "wall", "pos": list(free[-1])})
        self.assertTrue(pump(everyone, lambda: self.synced(a)))
        self.assertIsNotNone(a.world.grid.tile(free[-1]).building)
        # qualquer um desfaz e encerra o turno
        a.submit({"op": "undo"})
        self.assertTrue(pump(everyone, lambda: self.synced(a) and self.host.seq == 4))
        self.assertIsNone(a.world.grid.tile(free[-1]).building)
        turn = self.host.world.turn
        a.submit({"op": "end_turn"})
        self.assertTrue(pump(everyone, lambda: self.host.world.turn == turn + 1 and self.synced(a)))
        self.assertEqual(a.desyncs, 0)

    def test_full_game_stays_in_sync_with_two_clients(self):
        a = self.connect()
        b = self.connect()
        everyone = [self.host, a, b]
        self.assertTrue(pump(everyone, lambda: len(a.player_ids) == 3))
        rng = random.Random(4)
        for turn in range(6):
            actor = everyone[turn % 3]
            world = actor.world
            for unit in sorted(world.grid.units(), key=lambda u: u.pos)[:2]:
                moves = sorted(world.unit_moves(unit))
                if moves:
                    actor.submit({"op": "move", "from": list(unit.pos), "to": list(rng.choice(moves))})
            actor.submit({"op": "end_turn"})
            self.assertTrue(pump(everyone, lambda: self.synced(a) and self.synced(b)
                                 and not self.host.turns.busy))
        self.assertEqual((a.desyncs, b.desyncs), (0, 0))

    def test_late_join_replays_history(self):
        self.host.submit({"op": "fog", "enabled": False})
        self.host.submit({"op": "end_turn"})
        self.host.turns.resolve_instantly()
        a = self.connect()
        self.assertEqual(a.world.turn, self.host.world.turn)
        self.assertFalse(a.world.fog.enabled)
        self.assertEqual(world_checksum(a.world), world_checksum(self.host.world))

    def test_cursors_are_shared(self):
        a = self.connect()
        a.send_cursor((3, 4))
        self.assertTrue(pump([self.host, a], lambda: self.host.peer_cursors.get(2) == (3, 4)))
        self.host.send_cursor((5, 6))
        self.assertTrue(pump([self.host, a], lambda: a.peer_cursors.get(1) == (5, 6)))

    def test_desync_triggers_resync(self):
        a = self.connect()
        a.world.resources["gold"] += 100  # corrompe o estado local
        self.host.submit({"op": "end_turn"})
        self.assertTrue(pump([self.host, a], lambda: a.desyncs == 1 and self.synced(a)))
        self.assertEqual(a.world.resources, self.host.world.resources)

    def test_host_new_game_and_disconnect(self):
        a = self.connect()
        self.assertFalse(a.new_game(GameSetup(1, True)))
        self.host.new_game(GameSetup(77, False))
        self.assertTrue(pump([self.host, a], lambda: a.world.seed == 77 and self.synced(a)))
        self.assertFalse(a.world.fog.enabled)
        self.host.close()
        self.assertTrue(pump([a], lambda: not a.connected))

    def test_mismatched_data_is_rejected(self):
        from game.net import ClientTransport
        raw = ClientTransport("127.0.0.1", self.host.port)
        try:
            raw.send({"t": "hello", "version": 1, "data": "different"})
            self.assertTrue(pump([self.host], lambda: not raw.inbox.empty()))
            _, kind, msg = raw.wait(2)
            self.assertEqual((kind, msg["t"]), ("msg", "error"))
            self.assertEqual(self.host.player_ids, [1])
        finally:
            raw.close()
        self.assertEqual(len(data_fingerprint()), 12)

    def test_connection_refused(self):
        with self.assertRaises(NetError):
            ClientSession("127.0.0.1:1", timeout=1)


if __name__ == "__main__":
    unittest.main()
