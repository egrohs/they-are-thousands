import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from game.config import AP_PER_TURN, MAX_TURNS
from game.stats import BUILD_SPECS, BUILDING_STATS, CRATE_SPECS
from game.entities import (InfectedHouse, Quarry, Ranger, Sawmill, Soldier, Tent, Wall, Watchtower,
                           ZombieSwarm)
from game.fog import FogOfWar
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


class WatchtowerTests(unittest.TestCase):
    def setUp(self):
        self.world = World(seed=11, fog_enabled=False)
        for t in self.world.grid:
            t.terrain, t.resource_amount = Terrain.GRASS, 0
            t.building = t.unit = t.swarm = None
        self.world.hq.pos = (20, 20)
        self.world.grid.place_building(self.world.hq)
        self.tower = Watchtower((6, 5))
        self.world.grid.place_building(self.tower)
        self.ranger = Ranger((5, 5))
        self.world.grid.place_unit(self.ranger)

    def enter(self):
        self.assertTrue(self.world.move_unit(self.ranger, (6, 5)))
        self.assertEqual(self.ranger.pos, (6, 5))
        self.assertIs(self.world.grid.tile((6, 5)).unit, self.ranger)

    def test_tower_is_buildable(self):
        self.assertIn("watchtower", BUILD_SPECS)
        self.assertTrue(self.tower.garrison)

    def test_tower_is_destination_not_passage(self):
        moves = self.world.unit_moves(self.ranger)
        self.assertEqual(moves.get((6, 5)), 1)
        for y in range(10):  # wall line behind the tower: no path through it
            if y != 5:
                self.world.grid.place_building(Wall((6, y)))
        self.assertNotIn((7, 5), self.world.unit_moves(self.ranger))

    def test_enter_and_leave_with_bonuses(self):
        base_range = self.ranger.attack_range
        base_vision = FogOfWar.vision_of(self.ranger)
        self.enter()
        self.assertIs(self.world.shelter_of(self.ranger), self.tower)
        self.assertEqual(self.world.unit_range(self.ranger), base_range + self.tower.range_bonus)
        self.world.fog.enabled = True
        self.world.update_fog()
        reach = max(base_vision, FogOfWar.vision_of(self.tower)) + self.tower.vision_bonus
        self.assertTrue(self.world.fog.is_visible((6 + reach, 5)))
        self.world.fog.enabled = False
        self.ranger.moved = False
        self.assertTrue(self.world.move_unit(self.ranger, (6, 6)))
        self.assertIs(self.world.grid.tile((6, 5)).building, self.tower)
        self.assertIsNone(self.world.grid.tile((6, 5)).unit)
        self.assertEqual(self.world.unit_range(self.ranger), base_range)

    def test_zombies_hit_tower_not_unit_and_expose_it(self):
        self.enter()
        swarm = ZombieSwarm((7, 5), 10, aggressive=True)
        self.world.grid.place_swarm(swarm)
        hp = self.ranger.hp
        for _ in range(10):
            if not self.tower.alive:
                break
            self.world.zombies_attack()
        self.assertFalse(self.tower.alive)
        self.assertEqual(self.ranger.hp, hp)
        self.assertIsNone(self.world.grid.tile((6, 5)).building)
        self.assertIs(self.world.grid.tile((6, 5)).unit, self.ranger)
        self.world.zombies_attack()
        self.assertLess(self.ranger.hp, hp)

    def test_garrison_auto_fires_only_if_idle(self):
        swarm = ZombieSwarm((6, 5 + self.world.unit_range(self.ranger) + self.tower.range_bonus), 5,
                            aggressive=True)
        self.world.grid.place_swarm(swarm)
        self.world.garrisons_fire()
        self.assertEqual(swarm.count, 5)  # not garrisoned yet
        self.enter()
        self.ranger.acted = True
        self.world.garrisons_fire()
        self.assertEqual(swarm.count, 5)
        self.ranger.acted = False
        self.world.garrisons_fire()
        self.assertLess(swarm.count, 5)
        self.assertTrue(self.ranger.acted)


class CrateTests(unittest.TestCase):
    def setUp(self):
        self.world = World(seed=11, fog_enabled=False)
        for t in self.world.grid:
            t.terrain, t.resource_amount = Terrain.GRASS, 0
            t.building = t.unit = t.swarm = t.crate = None
        self.world.hq.pos = (20, 20)
        self.world.grid.place_building(self.world.hq)
        self.unit = Ranger((5, 5))
        self.world.grid.place_unit(self.unit)

    def test_random_maps_have_crates_outside_base(self):
        for seed in range(10):
            w = World(seed=seed)
            crates = [t for t in w.grid if t.crate]
            self.assertEqual(len(crates), w.crates_total)
            self.assertGreater(len(crates), 0, seed)
            for t in crates:
                self.assertTrue(t.terrain.passable)
                self.assertIsNone(t.building)
                self.assertIsNone(t.unit)
                self.assertGreaterEqual(Grid.chebyshev(t.pos, w.center), CRATE_SPECS[t.crate].min_dist)

    def test_crates_do_not_change_map_generation(self):
        a, b = World(seed=5), World(seed=5)
        self.assertEqual([(t.terrain, t.crate) for t in a.grid], [(t.terrain, t.crate) for t in b.grid])

    def test_unit_collects_crate_on_path(self):
        self.world.grid.tile((6, 5)).crate = "supplies"
        before = dict(self.world.resources)
        self.assertTrue(self.world.move_unit(self.unit, (7, 5)))
        self.assertIsNone(self.world.grid.tile((6, 5)).crate)
        for k, v in CRATE_SPECS["supplies"].loot.items():
            self.assertEqual(self.world.resources[k], before[k] + v)
        self.assertEqual(self.world.crates_found, 1)
        self.assertEqual(self.world.ap, AP_PER_TURN)  # coletar não gasta AP

    def test_crates_do_not_block_and_alarm_makes_noise(self):
        self.world.grid.tile((5, 6)).crate = "cache"
        self.assertIn((5, 6), self.world.unit_moves(self.unit))
        self.world.move_unit(self.unit, (5, 6))
        self.assertTrue(any(n.pos == (5, 6) and n.radius == CRATE_SPECS["cache"].noise
                            for n in self.world.pending_noise))

    def test_hidden_until_explored_and_map_roundtrip(self):
        from game.maps import build_grid, grid_to_data
        self.world.grid.tile((2, 2)).crate = "gold"
        grid, _ = build_grid(grid_to_data(self.world.grid, "t"))
        self.assertEqual(grid.tile((2, 2)).crate, "gold")
        fogged = World(seed=3, fog_enabled=True)
        far = next(t for t in fogged.grid if t.crate)
        self.assertFalse(fogged.fog.is_explored(far.pos))


class HarvesterTests(unittest.TestCase):
    def setUp(self):
        self.world = World(seed=11, fog_enabled=False)
        for t in self.world.grid:
            t.terrain, t.resource_amount = Terrain.GRASS, 0
            t.building = t.unit = t.swarm = t.crate = None
        self.world.hq.pos = (12, 12)
        self.world.grid.place_building(self.world.hq)
        for t in self.world.grid:
            if t.x <= 1:
                t.terrain, t.resource_amount = Terrain.FOREST, 5

    def test_sawmill_yield_scales_with_forest_and_caps(self):
        spec = BUILDING_STATS["sawmill"]
        mill = Sawmill((3, 5))  # raio 2 alcança as colunas x=1 (5 tiles de floresta)
        self.world.grid.place_building(mill)
        tiles = self.world.harvest_claims()[mill]
        self.assertEqual(len(tiles), 5)
        self.assertEqual(self.world.harvest_yield("sawmill", 5), min(spec.harvest_max, 5 // spec.harvest_tiles))
        mill2 = Sawmill((2, 15))  # 10 florestas: limitado ao máximo
        self.world.grid.place_building(mill2)
        self.assertEqual(self.world.harvest_yield("sawmill", len(self.world.harvest_claims()[mill2])),
                         spec.harvest_max)

    def test_overlapping_harvesters_share_tiles(self):
        a, b = Sawmill((2, 5)), Sawmill((2, 6))
        self.world.grid.place_building(a)
        self.world.grid.place_building(b)
        claims = self.world.harvest_claims()
        self.assertFalse(set(claims[a]) & set(claims[b]))
        self.assertEqual(len(claims[a]) + len(claims[b]), 12)  # união das áreas (x=0..1, y=3..8)
        tiles, _ = self.world.harvest_preview("sawmill", (2, 7))
        self.assertFalse(set(tiles) & (set(claims[a]) | set(claims[b])))

    def test_end_round_produces_wood_and_stone_without_depleting(self):
        for y in range(10, 13):
            self.world.grid.tile((16, y)).terrain = Terrain.ROCK
            self.world.grid.tile((16, y)).resource_amount = 4
        self.world.grid.place_building(Sawmill((2, 5)))
        self.world.grid.place_building(Quarry((15, 11)))
        prod = self.world.production()
        self.assertGreater(prod["wood"], 0)
        self.assertEqual(prod["stone"], 1)  # 3 pedreiras / 2 por unidade
        before = dict(self.world.resources)
        self.world.end_round()
        self.assertEqual(self.world.resources["wood"], before["wood"] + prod["wood"])
        self.assertEqual(self.world.resources["stone"], before["stone"] + prod["stone"])
        self.assertEqual(self.world.grid.tile((16, 11)).resource_amount, 4)

    def test_buildable_in_territory(self):
        self.assertIn("sawmill", BUILD_SPECS)
        self.assertIn("quarry", BUILD_SPECS)
        self.world.resources.update(gold=50, wood=50, stone=50)
        self.assertTrue(self.world.build("quarry", (13, 12)))
        self.assertIsInstance(self.world.grid.tile((13, 12)).building, Quarry)


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

    def test_darkness_layer_hides_far_explored_tiles(self):
        fog = self.world.fog
        far = (0, 0)
        fog.explored.add(far)
        fog.update()
        self.assertTrue(fog.is_explored(far))
        self.assertFalse(fog.is_known(far))
        self.assertTrue(fog.is_dark(far))
        # memória: explorado, fora da visão, mas a até visão + margem de um aliado
        sx, sy = self.soldier.pos
        r = FogOfWar.vision_of(self.soldier)
        for u in list(self.world.grid.units()):
            if u is not self.soldier:
                self.world.grid.remove_unit(u)
        for b in list(self.world.grid.buildings()):
            self.world.grid.remove_building(b)
        near = (sx + r + 1, sy)
        fog.explored.add(near)
        fog.update()
        self.assertFalse(fog.is_visible(near))
        self.assertTrue(fog.is_known(near))
        self.assertFalse(fog.is_dark(near))
        # unidade se afasta: o tile cai na escuridão; volta e ele reaparece
        self.world.grid.remove_unit(self.soldier)
        fog.update()
        self.assertTrue(fog.is_dark(near))
        self.world.grid.place_unit(self.soldier)
        fog.update()
        self.assertTrue(fog.is_known(near))

    def test_darkness_disabled_with_fog(self):
        fog = self.world.fog
        fog.explored.add((0, 0))
        fog.update()
        fog.enabled = False
        self.assertFalse(fog.is_dark((0, 0)))
        self.assertTrue(fog.is_known((0, 0)))


class UndoTests(unittest.TestCase):
    def setUp(self):
        self.world = World(seed=11, fog_enabled=False)
        for t in self.world.grid:
            t.terrain, t.resource_amount, t.crate = Terrain.GRASS, 0, None
            t.building = t.unit = t.swarm = None
        self.world.hq.pos = self.world.center
        self.world.grid.place_building(self.world.hq)
        self.world.resources.update(gold=50, wood=50, stone=50)
        cx, cy = self.world.center
        self.soldier = Soldier((cx + 2, cy))
        self.world.grid.place_unit(self.soldier)

    def test_empty_history(self):
        self.assertFalse(self.world.can_undo)
        self.assertFalse(self.world.undo())

    def test_undo_build_restores_resources_ap_and_tile(self):
        world = self.world
        cx, cy = world.center
        before = (dict(world.resources), world.ap, len(world.pending_noise))
        self.assertTrue(world.build("wall", (cx - 2, cy)))
        self.assertTrue(world.can_undo)
        self.assertTrue(world.undo())
        self.assertIsNone(world.grid.tile((cx - 2, cy)).building)
        self.assertEqual((dict(world.resources), world.ap, len(world.pending_noise)), before)
        self.assertFalse(world.can_undo)

    def test_failed_action_is_not_recorded(self):
        self.assertFalse(self.world.build("wall", (0, 0)))
        self.assertFalse(self.world.can_undo)

    def test_undo_move_and_multiple_steps(self):
        world = self.world
        cx, cy = world.center
        identity = id(world)
        start = self.soldier.pos
        self.assertTrue(world.move_unit(self.soldier, (cx + 4, cy)))
        self.assertTrue(world.build("wall", (cx - 2, cy)))
        self.assertEqual(len(world.history), 2)
        self.assertTrue(world.undo())
        self.assertIsNone(world.grid.tile((cx - 2, cy)).building)
        unit = world.grid.tile((cx + 4, cy)).unit
        self.assertTrue(unit.moved)
        self.assertTrue(world.undo())
        self.assertIsNone(world.grid.tile((cx + 4, cy)).unit)
        unit = world.grid.tile(start).unit
        self.assertIsInstance(unit, Soldier)
        self.assertFalse(unit.moved)
        self.assertEqual(id(world), identity)

    def test_undo_attack_restores_swarm(self):
        world = self.world
        sx, sy = self.soldier.pos
        world.grid.place_swarm(ZombieSwarm((sx + 2, sy), 6))
        self.assertTrue(world.unit_attack(self.soldier, (sx + 2, sy)))
        kills = world.zombies_killed
        self.assertTrue(world.undo())
        self.assertEqual(world.grid.tile((sx + 2, sy)).swarm.count, 6)
        self.assertFalse(world.grid.tile((sx, sy)).unit.acted)
        self.assertLessEqual(world.zombies_killed, kills)

    def test_history_cleared_at_end_of_turn(self):
        world = self.world
        cx, cy = world.center
        world.build("wall", (cx - 2, cy))
        tm = TurnManager(world, phase_delay=0)
        tm.end_player_turn()
        tm.resolve_instantly()
        self.assertFalse(world.can_undo)

    def test_revealing_fog_locks_history(self):
        world = self.world
        cx, cy = world.center
        world.fog.enabled = True
        world.update_fog()
        self.assertTrue(world.build("wall", (cx - 2, cy)))
        self.assertTrue(world.can_undo)
        far = (cx + 2 + self.soldier.move_range, cy)
        self.assertGreater(len(set(world.fog.explored)), 0)
        self.assertTrue(world.move_unit(self.soldier, far))
        self.assertFalse(world.can_undo)
        self.assertIsNotNone(world.grid.tile((cx - 2, cy)).building)

    def test_move_without_reveal_is_undoable_with_fog(self):
        world = self.world
        cx, cy = world.center
        world.fog.enabled = True
        world.fog.explored.update(t.pos for t in world.grid)
        world.update_fog()
        self.assertTrue(world.move_unit(self.soldier, (cx + 3, cy)))
        self.assertTrue(world.can_undo)


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
