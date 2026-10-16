import shutil
import tempfile
import unittest
from pathlib import Path

from game.config import DATA_DIR
from game.entities import Ballista, CommandCenter, InfectedHouse, Ranger, Tesla, ZombieSwarm
from game.stats import (BUILD_SPECS, BUILDING_STATS, UNIT_SPECS, VISION_RADIUS, ZOMBIE_SPECS,
                        StatsError, load_stats)


class StatsFilesTest(unittest.TestCase):
    def test_real_files_load(self):
        stats = load_stats(DATA_DIR)
        self.assertEqual(set(stats.units), {"soldier", "ranger"})
        self.assertIn("walker", stats.zombies)
        self.assertEqual(set(BUILD_SPECS), {"wall", "tent", "ballista", "tesla", "watchtower", "sawmill", "quarry"})
        self.assertEqual((BUILDING_STATS["sawmill"].harvest, BUILDING_STATS["quarry"].harvest), ("wood", "stone"))
        tower = BUILDING_STATS["watchtower"]
        self.assertTrue(tower.garrison)
        self.assertGreater(tower.range_bonus, 0)
        self.assertGreater(tower.vision_bonus, 0)
        self.assertFalse(BUILDING_STATS["ballista"].garrison)
        self.assertEqual(BUILD_SPECS["ballista"].cost, {"gold": 6, "wood": 4, "stone": 3})
        self.assertTrue(ZOMBIE_SPECS["harpy"].flying)
        self.assertEqual(ZOMBIE_SPECS["walker"].color, (0x69, 0x24, 0x24))
        self.assertEqual(VISION_RADIUS["ranger"], UNIT_SPECS["ranger"].vision)

    def test_entities_use_csv_values(self):
        self.assertEqual(CommandCenter((0, 0)).max_hp, BUILDING_STATS["hq"].hp)
        self.assertEqual(CommandCenter((0, 0)).build_radius, BUILDING_STATS["hq"].build_radius)
        self.assertEqual(Tesla((0, 0)).build_radius, BUILDING_STATS["tesla"].build_radius)
        b = Ballista((0, 0))
        self.assertEqual((b.attack_range, b.damage), (BUILDING_STATS["ballista"].attack_range,
                                                      BUILDING_STATS["ballista"].damage))
        self.assertEqual(InfectedHouse((0, 0)).stats.spawn, BUILDING_STATS["infected"].spawn)
        self.assertEqual(Ranger((0, 0)).move_range, UNIT_SPECS["ranger"].move)
        self.assertEqual(ZombieSwarm((0, 0), 99, kind="brute").count, ZOMBIE_SPECS["brute"].max_stack)


class StatsParsingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for name in ("buildings.csv", "units.csv", "zombies.csv", "waves.csv", "crates.csv",
                     "heroes.csv", "skills.csv"):
            shutil.copy(DATA_DIR / name, self.tmp / name)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _edit(self, name, old, new):
        path = self.tmp / name
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def test_semicolon_and_decimal_comma(self):
        (self.tmp / "units.csv").write_text(
            "\ufeffid;name;symbol;hp;move;attack_range;damage;noise;vision\n"
            "soldier;Soldado;S;7;3;3;4;6;4\nranger;Ranger;R;5;4;4;2;1;6\n", encoding="utf-8")
        text = (self.tmp / "zombies.csv").read_text(encoding="utf-8")
        lines = text.splitlines()
        rows = [lines[0].replace(",", ";")]
        rows += ["walker;Errante;Z;1;2;0,5;10;1;1;0;0;#692424;Comum"]
        (self.tmp / "zombies.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaises(StatsError) as ctx:  # START_SWARM_TYPES usa tipos removidos
            load_stats(self.tmp)
        self.assertIn("runner", str(ctx.exception))
        rows += [f"{k};X;X;1;2;0,75;5;1;1;sim;0;#000000;" for k in
                 ("runner", "brute", "harpy", "venom")]
        (self.tmp / "zombies.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        stats = load_stats(self.tmp)
        self.assertEqual(stats.zombies["walker"].attack, 0.5)
        self.assertEqual(stats.zombies["harpy"].attack, 0.75)
        self.assertTrue(stats.zombies["venom"].flying)
        self.assertEqual(stats.units["ranger"].vision, 6)

    def test_missing_required_id(self):
        text = (self.tmp / "units.csv").read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if not ln.startswith("ranger,")]
        (self.tmp / "units.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(StatsError, "units.csv.*ranger"):
            load_stats(self.tmp)

    def test_missing_column(self):
        self._edit("units.csv", ",vision", "")
        with self.assertRaisesRegex(StatsError, "vision"):
            load_stats(self.tmp)

    def test_bad_value_reports_file_and_line(self):
        self._edit("buildings.csv", "wall,Muro,M,1,1,0,2,0,10", "wall,Muro,M,1,1,0,2,0,muito")
        with self.assertRaisesRegex(StatsError, r"buildings.csv linha 4, coluna 'hp'"):
            load_stats(self.tmp)

    def test_negative_or_zero_hp_rejected(self):
        self._edit("buildings.csv", "wall,Muro,M,1,1,0,2,0,10", "wall,Muro,M,1,1,0,2,0,0")
        with self.assertRaisesRegex(StatsError, "hp"):
            load_stats(self.tmp)

    def test_crate_without_loot_rejected(self):
        with (self.tmp / "crates.csv").open("a", encoding="utf-8") as f:
            f.write("empty,Vazia,VZ,1,0,0,0,0,6,#000000,\n")
        with self.assertRaisesRegex(StatsError, "empty"):
            load_stats(self.tmp)

    def test_bad_harvest_rejected(self):
        self._edit("buildings.csv", ",wood,2,2,4,", ",ouro,2,2,4,")
        with self.assertRaisesRegex(StatsError, "sawmill"):
            load_stats(self.tmp)

    def test_crates_load(self):
        stats = load_stats(self.tmp)
        self.assertIn("supplies", stats.crates)
        self.assertTrue(all(c.loot for c in stats.crates.values()))

    def test_unknown_building_rejected(self):
        with (self.tmp / "buildings.csv").open("a", encoding="utf-8") as f:
            f.write("castle,Castelo,K,1,5,0,0,0,30,0,0,0,0,0,0,0,0,0,0,0,,0,0,0,\n")
        with self.assertRaisesRegex(StatsError, "castle"):
            load_stats(self.tmp)

    def test_new_zombie_type_is_data_driven(self):
        with (self.tmp / "zombies.csv").open("a", encoding="utf-8") as f:
            f.write("tank,Tanque,K,5,1,2,2,1,3,0,0,#334455,Muito resistente\n")
        stats = load_stats(self.tmp)
        self.assertEqual(stats.zombies["tank"].hp, 5)
        self.assertEqual(stats.zombies["tank"].color, (0x33, 0x44, 0x55))

    def test_wave_schedule_loads(self):
        stats = load_stats(self.tmp)
        self.assertTrue(stats.waves)
        self.assertEqual([w.turn for w in stats.waves], sorted(w.turn for w in stats.waves))
        self.assertEqual(len({w.turn for w in stats.waves if w.final}), 1)

    def test_wave_with_unknown_kind_or_direction(self):
        with (self.tmp / "waves.csv").open("a", encoding="utf-8") as f:
            f.write("5,N,dragon,1,3,0,\n")
        with self.assertRaisesRegex(StatsError, "waves.csv linha .*dragon"):
            load_stats(self.tmp)
        self._edit("waves.csv", "5,N,dragon", "5,NE,walker")
        with self.assertRaisesRegex(StatsError, "direction"):
            load_stats(self.tmp)

    def test_fixed_direction_is_respected(self):
        (self.tmp / "waves.csv").write_text(
            "turn,direction,kind,swarms,size,final\n4,L,walker,2,3,0\n", encoding="utf-8")
        stats = load_stats(self.tmp)
        from game.world import World
        world = World(seed=5)
        plan = world._plan_waves(stats.waves)
        self.assertEqual(plan[0].entry_points[0][0], 3)
        self.assertEqual(plan[0].entry_points[0][1][0], world.grid.width - 1)


if __name__ == "__main__":
    unittest.main()
