import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from game.config import AP_PER_TURN, BUILD_SPECS, MAX_TURNS
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
