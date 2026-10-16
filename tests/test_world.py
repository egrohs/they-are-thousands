import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from game.config import AP_PER_TURN, MAX_TURNS
from game.stats import BUILD_SPECS
from game.entities import InfectedHouse, Ranger, Soldier, Tent, Wall, ZombieSwarm
from game.grid import Grid, Terrain
from game.turns import Phase, TurnManager
from game.world import World


def clear_swarms(world: World) -> None:
    for s in world.grid.swarms():
        world.grid.remove_swarm(s)


class GridTests(unittest.TestCase):
    def test_distances(self):
        self.assertEqual(Grid.manhattan((0, 0), (3, 4)), 7)
        self.assertEqual(Grid.chebyshev((0, 0), (3, 4)), 4)

    def test_dijkstra_avoids_water(self):
        g = Grid(5, 5)
        for y in range(4):
            g.tile((2, y)).terrain = Terrain.WATER
        field = g.dijkstra([(4, 0)], lambda p: None if not g.tile(p).terrain.passable else 1.0)
        self.assertEqual(field[(0, 0)], 12)
        self.assertNotIn((2, 0), field)

    def test_only_grass_is_passable(self):
        self.assertTrue(Terrain.GRASS.passable)
        for terrain in (Terrain.FOREST, Terrain.ROCK, Terrain.WATER):
            self.assertFalse(terrain.passable, terrain)


class TerrainBlockingTests(unittest.TestCase):
    def setUp(self):
        self.world = World(seed=11, fog_enabled=False)
        for t in self.world.grid:
            t.terrain, t.resource_amount = Terrain.GRASS, 0
            t.building = t.unit = t.swarm = None
        self.world.hq.pos = (20, 20)
        self.world.grid.place_building(self.world.hq)

    def test_units_cannot_cross_forest_rock_or_water(self):
        unit = Soldier((5, 5))
        self.world.grid.place_unit(unit)
        for x, y in ((6, 5), (4, 5), (5, 6)):
            self.world.grid.tile((x, y)).terrain = Terrain.FOREST
        self.world.grid.tile((5, 4)).terrain = Terrain.ROCK
        self.assertEqual(self.world.unit_moves(unit), {})
        self.world.grid.tile((5, 4)).terrain = Terrain.WATER
        self.assertEqual(self.world.unit_moves(unit), {})

    def test_units_path_around_obstacles_and_still_gather(self):
        unit = Soldier((5, 5))
        self.world.grid.place_unit(unit)
        for y in range(0, 5):
            self.world.grid.tile((6, y)).terrain = Terrain.ROCK
            self.world.grid.tile((6, y)).resource_amount = 5
        moves = self.world.unit_moves(unit)
        self.assertNotIn((6, 4), moves)
        self.assertEqual(moves.get((7, 5)), 2)
        self.assertIn((6, 4), self.world.gather_targets(unit))

    def test_zombies_cannot_cross_blocking_terrain(self):
        for kind in ("walker", "harpy"):
            swarm = ZombieSwarm((10, 10), 3, aggressive=True, kind=kind)
            self.world.grid.place_swarm(swarm)
            for n in self.world.grid.neighbors4((10, 10)):
                self.world.grid.tile(n).terrain = Terrain.FOREST
            self.world.zombies_move()
            self.assertEqual(swarm.pos, (10, 10), kind)
            self.world.grid.remove_swarm(swarm)

    def test_generated_maps_have_no_isolated_pockets(self):
        for seed in range(15):
            w = World(seed=seed)
            passable = lambda p: w.grid.tile(p).terrain.passable  # noqa: E731
            reach = w.grid.bfs_reachable(w.center, 999, passable)
            isolated = [t.pos for t in w.grid if t.terrain.passable and t.pos not in reach]
            self.assertEqual(isolated, [], seed)


class ZombieTypeTests(unittest.TestCase):
    def setUp(self):
        self.world = World(seed=7, fog_enabled=False)
        for t in self.world.grid:
            t.terrain, t.resource_amount = Terrain.GRASS, 0
            t.building = t.unit = t.swarm = None
        self.tent = Tent((5, 1))
        self.world.grid.place_building(self.tent)

    def place(self, kind, pos, count=3):
        s = ZombieSwarm(pos, count, aggressive=True, kind=kind)
        self.world.grid.place_swarm(s)
        return s

    def wall_row(self, y):
        for x in range(self.world.grid.width):
            self.world.grid.place_building(Wall((x, y)))

    def test_brute_has_multiple_hp_and_wounds(self):
        s = ZombieSwarm((0, 0), 3, kind="brute")
        self.assertEqual(s.kill(4), 1)
        self.assertEqual(s.wounds, 1)
        self.assertEqual(s.kill(2), 1)
        self.assertEqual((s.count, s.wounds), (1, 0))

    def test_brute_double_damage_vs_structures(self):
        s = ZombieSwarm((0, 0), 2, kind="brute")
        self.assertEqual(s.damage_against(False), 3)
        self.assertEqual(s.damage_against(True), 6)

    def test_stack_limit_per_type(self):
        self.assertEqual(ZombieSwarm((0, 0), 10, kind="brute").count, 4)

    def test_runner_is_faster_than_walker(self):
        runner = self.place("runner", (5, 12))
        walker = self.place("walker", (7, 12))
        self.world.zombies_move()
        self.assertEqual(runner.pos, (5, 9))
        self.assertEqual(Grid.manhattan(walker.pos, (7, 12)), 2)

    def test_different_types_do_not_merge(self):
        self.place("walker", (5, 3), 2)
        runner = self.place("runner", (5, 4), 2)
        self.world.zombies_move()
        kinds = sorted(s.kind for s in self.world.grid.swarms())
        self.assertEqual(kinds, ["runner", "walker"])
        self.assertEqual(runner.count, 2)

    def test_harpy_leaps_over_walls_walker_does_not(self):
        self.wall_row(4)
        harpy = self.place("harpy", (5, 6))
        walker = self.place("walker", (9, 6))
        self.world.zombies_move()
        self.assertLess(harpy.pos[1], 4)
        self.assertGreater(walker.pos[1], 4)

    def test_venom_spits_from_range(self):
        venom = self.place("venom", (5, 3), 2)
        self.world.zombies_move()
        self.assertEqual(venom.pos, (5, 3))
        hp = self.tent.hp
        self.world.zombies_attack()
        self.assertLess(self.tent.hp, hp)
        self.assertEqual(self.world.effects[-1].color_key, "spit")

    def test_runner_hears_farther(self):
        walker = ZombieSwarm((10, 10), 2)
        runner = ZombieSwarm((10, 15), 2, kind="runner")
        for s in (walker, runner):
            s.aggressive = False
            self.world.grid.place_swarm(s)
        self.world.emit_noise((10, 20), 4, "teste")
        self.world.propagate_noise()
        self.assertTrue(runner.aggressive)
        self.assertFalse(walker.aggressive)

    def test_waves_spawn_typed_swarms(self):
        from game.world import PlannedWave, WaveGroup
        wave = PlannedWave(5, False, [WaveGroup(0, (12, 0), "harpy", 1, 3),
                                      WaveGroup(0, (12, 0), "brute", 2, 2)])
        spawned = self.world._spawn_wave(wave)
        self.assertEqual(spawned, {"harpy": 1, "brute": 2})
        self.assertTrue(wave.spawned)
        self.assertEqual({s.kind for s in self.world.grid.swarms()}, {"harpy", "brute"})
        # todos entram pela borda norte, perto do ponto anunciado
        for s in self.world.grid.swarms():
            self.assertLess(s.pos[1], 2)
            self.assertLessEqual(abs(s.pos[0] - 12), 4)

    def test_wave_plan_is_announced_and_deterministic(self):
        plan = self.world.waves
        self.assertTrue(plan)
        for wave in plan:
            for side, anchor in wave.entry_points:
                if side == 0:
                    self.assertEqual(anchor[1], 0)
                elif side == 1:
                    self.assertEqual(anchor[1], self.world.grid.height - 1)
                elif side == 2:
                    self.assertEqual(anchor[0], 0)
                else:
                    self.assertEqual(anchor[0], self.world.grid.width - 1)
        normal = [w for w in plan if not w.final]
        self.assertTrue(all(len(w.entry_points) == 1 for w in normal))
        again = World(seed=self.world.seed).waves
        self.assertEqual([(w.turn, w.entry_points) for w in plan],
                         [(w.turn, w.entry_points) for w in again])

    def test_scheduled_wave_spawns_at_announced_edge(self):
        world = self.world
        clear_swarms(world)
        wave = world.next_wave
        world.turn = wave.turn
        world.end_round()
        self.assertTrue(wave.spawned)
        sides = {side for side, _ in wave.entry_points}
        for s in world.grid.swarms():
            on_edge = {0: s.pos[1] < 2, 1: s.pos[1] >= world.grid.height - 2,
                       2: s.pos[0] < 2, 3: s.pos[0] >= world.grid.width - 2}
            self.assertTrue(any(on_edge[d] for d in sides), s.pos)


class WorldTests(unittest.TestCase):
    def setUp(self):
        self.world = World(seed=123)
        clear_swarms(self.world)
        self.cx, self.cy = self.world.center

    def test_build_spends_resources_and_emits_noise(self):
        pos = (self.cx + 1, self.cy - 1)
        wood = self.world.resources["wood"]
        self.assertTrue(self.world.build("wall", pos))
        self.assertIsInstance(self.world.grid.tile(pos).building, Wall)
        self.assertEqual(self.world.ap, AP_PER_TURN - BUILD_SPECS["wall"].ap)
        self.assertEqual(self.world.resources["wood"], wood - BUILD_SPECS["wall"].wood)
        self.assertEqual(len(self.world.pending_noise), 1)

    def test_build_rejects_out_of_range(self):
        ok, _ = self.world.can_build("wall", (0, 0))
        self.assertFalse(ok)

    def test_only_tesla_expands_territory(self):
        edge = (self.cx + 4, self.cy)
        beyond = (self.cx + 6, self.cy)
        for p in (edge, beyond, (self.cx + 5, self.cy)):
            t = self.world.grid.tile(p)
            t.terrain, t.building, t.unit = Terrain.GRASS, None, None
        self.world.resources.update(gold=50, wood=50, stone=50)
        self.assertFalse(self.world.in_build_range(beyond))
        self.assertTrue(self.world.build("tent", edge))
        self.assertFalse(self.world.in_build_range(beyond))
        self.world.grid.remove_building(self.world.grid.tile(edge).building)
        self.assertTrue(self.world.build("tesla", edge))
        self.assertTrue(self.world.in_build_range(beyond))
        self.assertTrue(self.world.can_build("wall", beyond)[0])

    def test_noise_alerts_swarm(self):
        swarm = ZombieSwarm((self.cx + 6, self.cy), 3)
        self.world.grid.place_swarm(swarm)
        self.world.emit_noise((self.cx + 1, self.cy), 6, "teste")
        self.world.propagate_noise()
        self.assertTrue(swarm.aggressive)
        self.assertEqual(swarm.noise_target, (self.cx + 1, self.cy))

    def test_unit_attack_kills_zombies(self):
        soldier = next(u for u in self.world.grid.units() if isinstance(u, Soldier))
        target = (soldier.pos[0] + 2, soldier.pos[1])
        if self.world.grid.tile(target).occupied:
            self.skipTest("tile ocupado")
        swarm = ZombieSwarm(target, 6)
        self.world.grid.place_swarm(swarm)
        self.assertTrue(self.world.unit_attack(soldier, target))
        self.assertEqual(swarm.count, 2)
        self.assertTrue(soldier.acted)

    def test_tent_becomes_infected_house_and_spawns(self):
        tent = next(b for b in self.world.grid.buildings() if isinstance(b, Tent))
        tent.hp = 0
        self.world.resolve_infection()
        house = self.world.grid.tile(tent.pos).building
        self.assertIsInstance(house, InfectedHouse)
        self.assertGreater(self.world.total_zombies, 0)

    def test_zombies_move_toward_colony_and_attack(self):
        ranger = next(u for u in self.world.grid.units() if isinstance(u, Ranger))
        start = (ranger.pos[0], ranger.pos[1] - 3)
        tile = self.world.grid.tile(start)
        tile.terrain = Terrain.GRASS
        tile.building = tile.unit = None
        for y in range(start[1] + 1, ranger.pos[1]):
            self.world.grid.tile((start[0], y)).terrain = Terrain.GRASS
        swarm = ZombieSwarm(start, 4, aggressive=True)
        self.world.grid.place_swarm(swarm)
        self.world.zombies_move()
        self.assertLess(Grid.manhattan(swarm.pos, ranger.pos), 3)
        self.world.zombies_move()
        self.assertEqual(Grid.manhattan(swarm.pos, ranger.pos), 1)
        hp = ranger.hp
        self.world.zombies_attack()
        self.assertLess(ranger.hp, hp)


class FogTests(unittest.TestCase):
    def setUp(self):
        self.world = World(seed=123)
        clear_swarms(self.world)
        self.soldier = next(u for u in self.world.grid.units() if isinstance(u, Soldier))

    def _clear_tile(self, pos):
        t = self.world.grid.tile(pos)
        t.terrain, t.building, t.unit, t.swarm = Terrain.GRASS, None, None, None

    def test_initial_visibility_and_exploration(self):
        fog = self.world.fog
        self.assertIn(self.world.center, fog.visible)
        self.assertNotIn((0, 0), fog.explored)
        self.assertFalse(fog.is_visible((0, 0)))

    def test_hidden_swarm_cannot_be_attacked_until_fog_disabled(self):
        self.soldier.attack_range = 20
        pos = (0, 0)
        self._clear_tile(pos)
        self.world.grid.place_swarm(ZombieSwarm(pos, 3))
        self.assertNotIn(pos, self.world.attack_targets(self.soldier))
        self.world.fog.enabled = False
        self.assertIn(pos, self.world.attack_targets(self.soldier))

    def test_ambush_interrupts_movement_through_fog(self):
        self.world.fog.visible.clear()
        self.world.fog.explored.clear()
        sx, sy = self.soldier.pos
        for i in range(1, 4):
            self._clear_tile((sx + i, sy))
        self.world.grid.place_swarm(ZombieSwarm((sx + 2, sy), 2))
        self.world.fog.visible.clear()
        self.world.fog.explored.clear()
        moves = self.world.unit_moves(self.soldier)
        self.assertIn((sx + 3, sy), moves)
        path = self.world._path_to(self.soldier.pos, (sx + 3, sy), moves)
        if (sx + 2, sy) not in path:
            self.skipTest("caminho alternativo não passa pelo enxame")
        self.world.move_unit(self.soldier, (sx + 3, sy))
        self.assertEqual(self.soldier.pos, (sx + 1, sy))
        self.assertTrue(self.soldier.moved)
        self.assertIn("Emboscada", self.world.log[-1])

    def test_explored_memory_persists(self):
        ranger = next(u for u in self.world.grid.units() if isinstance(u, Ranger))
        old = set(self.world.fog.visible)
        self.world.grid.remove_unit(ranger)
        self.world.update_fog()
        self.assertTrue(old <= self.world.fog.explored)


class TurnFlowTests(unittest.TestCase):
    def test_full_game_runs_to_completion_deterministically(self):
        results = []
        for _ in range(2):
            world = World(seed=7)
            turns = TurnManager(world, phase_delay=0)
            safety = 0
            while not world.game_over and safety < 100:
                self.assertIs(turns.phase, Phase.PLAYER)
                self.assertEqual(world.ap, AP_PER_TURN)
                turns.end_player_turn()
                turns.resolve_instantly()
                safety += 1
            self.assertIs(turns.phase, Phase.GAME_OVER)
            self.assertLessEqual(world.turn, MAX_TURNS)
            results.append((world.turn, world.victory, world.total_zombies, world.log[-1]))
        self.assertEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
