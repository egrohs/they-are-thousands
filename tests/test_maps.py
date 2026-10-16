import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from game.editor import MapEditor, blank_map_data
from game.entities import CommandCenter
from game.grid import Terrain
from game.maps import MapError, build_grid, grid_to_data, list_maps, load_map, save_map
from game.turns import TurnManager
from game.world import World


class MapFileTests(unittest.TestCase):
    def test_round_trip_random_world(self):
        w = World(seed=11, fog_enabled=False)
        data = grid_to_data(w.grid, "teste")
        again = World(seed=1, fog_enabled=False, map_data=data)
        self.assertEqual(grid_to_data(again.grid, "teste"), data)
        self.assertEqual(again.map_name, "teste")
        self.assertEqual(again.hq.pos, w.hq.pos)

    def test_requires_exactly_one_hq(self):
        data = blank_map_data()
        data["buildings"] = []
        with self.assertRaises(MapError):
            build_grid(data)
        data["buildings"] = [{"kind": "hq", "pos": [1, 1]}, {"kind": "hq", "pos": [3, 3]}]
        with self.assertRaises(MapError):
            build_grid(data)

    def test_rejects_invalid_content(self):
        bad_terrain = blank_map_data()
        bad_terrain["terrain"] = ["X" * 24] + bad_terrain["terrain"][1:]
        bad_swarm = blank_map_data()
        bad_swarm["swarms"] = [{"kind": "dragon", "count": 2, "pos": [0, 0]}]
        overlap = blank_map_data()
        overlap["units"] = [{"kind": "soldier", "pos": [12, 12]}]
        out = blank_map_data()
        out["units"] = [{"kind": "ranger", "pos": [99, 0]}]
        for data in (bad_terrain, bad_swarm, overlap, out, [], {"version": 9}):
            with self.assertRaises(MapError):
                build_grid(data)

    def test_save_list_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = blank_map_data("Minha Fortaleza!")
            path = save_map(data, Path(tmp))
            self.assertEqual(path.name, "minha_fortaleza.json")
            self.assertEqual(list_maps(Path(tmp)), [path])
            self.assertEqual(load_map(path)["name"], "Minha Fortaleza!")
            path.write_text("{ quebrado", encoding="utf-8")
            with self.assertRaises(MapError):
                load_map(path)


class MapEditorTests(unittest.TestCase):
    def setUp(self):
        self.ed = MapEditor()
        self.grid = self.ed.world.grid
        self.hq = self.ed.world.hq.pos

    def test_paint_terrain_with_brush_and_resources(self):
        self.ed.tool, self.ed.amount, self.ed.brush = "t:forest", 7, 3
        self.assertTrue(self.ed.apply((2, 2)))
        for x in range(1, 4):
            for y in range(1, 4):
                t = self.grid.tile((x, y))
                self.assertEqual((t.terrain, t.resource_amount), (Terrain.FOREST, 7))
        self.assertEqual(self.grid.tile((4, 2)).terrain, Terrain.GRASS)

    def test_place_entities_replace_and_clamp_stack(self):
        self.ed.tool = "b:wall"
        self.assertTrue(self.ed.apply((3, 3)))
        self.ed.tool, self.ed.amount = "z:brute", 10
        self.assertTrue(self.ed.apply((3, 3)))
        t = self.grid.tile((3, 3))
        self.assertIsNone(t.building)
        self.assertEqual((t.swarm.kind, t.swarm.count), ("brute", 4))

    def test_water_clears_tile_and_blocks_units(self):
        self.ed.tool = "u:soldier"
        self.ed.apply((5, 5))
        self.ed.tool = "t:water"
        self.ed.apply((5, 5))
        self.assertIsNone(self.grid.tile((5, 5)).unit)
        self.ed.tool = "u:ranger"
        self.assertFalse(self.ed.apply((5, 5)))

    def test_hq_is_unique_and_protected(self):
        self.ed.tool = "erase"
        self.assertFalse(self.ed.apply(self.hq))
        self.ed.tool = "t:water"
        self.assertFalse(self.ed.apply(self.hq))
        self.ed.tool = "b:hq"
        self.assertTrue(self.ed.apply((2, 20)))
        hqs = [b for b in self.grid.buildings() if isinstance(b, CommandCenter)]
        self.assertEqual([b.pos for b in hqs], [(2, 20)])
        self.assertIs(self.ed.world.hq, hqs[0])
        self.assertIsNone(self.ed.validate())

    def test_erase_layers(self):
        self.ed.tool = "t:rock"
        self.ed.apply((1, 1))
        self.ed.tool = "z:walker"
        self.ed.apply((1, 1))
        self.ed.tool = "erase"
        self.ed.apply((1, 1))
        self.assertIsNone(self.grid.tile((1, 1)).swarm)
        self.assertEqual(self.grid.tile((1, 1)).terrain, Terrain.ROCK)
        self.ed.apply((1, 1))
        self.assertEqual(self.ed.world.grid.tile((1, 1)).terrain, Terrain.GRASS)

    def test_stroke_undo_redo(self):
        self.ed.begin_stroke()
        self.ed.tool = "b:wall"
        for x in range(2, 7):
            self.ed.apply((x, 2))
        self.ed.end_stroke()
        walls = lambda: sum(b.kind == "wall" for b in self.ed.world.grid.buildings())  # noqa: E731
        self.assertEqual(walls(), 5)
        self.assertTrue(self.ed.undo())
        self.assertEqual(walls(), 0)
        self.assertTrue(self.ed.redo())
        self.assertEqual(walls(), 5)
        self.ed.begin_stroke()
        self.ed.apply((2, 2))  # sem mudança: não cria passo de desfazer
        self.ed.end_stroke()
        self.assertEqual(len(self.ed.undo_stack), 1)

    def test_edited_map_is_playable(self):
        self.ed.tool = "u:soldier"
        self.ed.apply((self.hq[0], self.hq[1] + 2))
        self.ed.tool, self.ed.amount = "z:runner", 4
        self.ed.apply((self.hq[0] + 3, self.hq[1]))
        world = World(seed=5, fog_enabled=False, map_data=self.ed.to_data())
        tm = TurnManager(world)
        tm.end_player_turn()
        tm.resolve_instantly()
        self.assertGreaterEqual(world.turn, 1)
        self.assertEqual({s.kind for s in world.grid.swarms()} - {"walker"}, {"runner"})


if __name__ == "__main__":
    unittest.main()
