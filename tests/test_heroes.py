import unittest

from game.config import (HERO_DEBUFF_TURNS, HERO_LEVEL_XP, HERO_RECOVERY_TURNS, HERO_REVIVE_AP)
from game.coop import GameSetup, Session, world_checksum
from game.entities import Hero, Soldier, Tent, ZombieSwarm
from game.grid import Terrain
from game.stats import HERO_SKILLS, HERO_SPECS, SKILL_SPECS
from game.world import World


def arena(seed: int = 3) -> World:
    """Mapa todo de campo, só com o CC no centro: posições controladas nos testes."""
    world = World(seed=seed, fog_enabled=False)
    for t in world.grid:
        t.terrain, t.resource_amount, t.crate = Terrain.GRASS, 0, None
        if t.swarm is not None:
            world.grid.remove_swarm(t.swarm)
        if t.unit is not None:
            world.grid.remove_unit(t.unit)
        if t.building is not None and t.building is not world.hq:
            world.grid.remove_building(t.building)
    world.history.clear()
    world.update_fog()
    return world


def hero(world: World, hero_id: str, pos, owner: int = 1) -> Hero:
    h = Hero(pos, hero_id, owner)
    world.heroes.append(h)
    world.grid.place_unit(h)
    return h


def swarm(world: World, pos, count: int = 3, kind: str = "walker") -> ZombieSwarm:
    s = ZombieSwarm(pos, count, aggressive=True, kind=kind)
    world.grid.place_swarm(s)
    return s


class HeroDataTests(unittest.TestCase):
    def test_roles_and_skills(self):
        self.assertEqual(set(HERO_SPECS), {"tank", "ranged", "rogue", "healer", "mage"})
        for hid, skills in HERO_SKILLS.items():
            self.assertTrue(1 <= len(skills) <= 3, hid)
        tank, dps = HERO_SPECS["tank"], HERO_SPECS["ranged"]
        self.assertGreater(tank.hp, max(h.hp for k, h in HERO_SPECS.items() if k != "tank"))
        self.assertGreater(tank.armor, 0)
        self.assertEqual(dps.damage, max(h.damage for h in HERO_SPECS.values()))
        self.assertEqual(HERO_SPECS["rogue"].noise, 0)
        self.assertGreater(HERO_SPECS["mage"].mana, 0)


class PickTests(unittest.TestCase):
    def test_pick_places_near_cc_one_per_player(self):
        world = World(seed=5, fog_enabled=False)
        self.assertTrue(world.pick_hero("tank", 1))
        tank = world.hero_of(1)
        self.assertIsNotNone(tank)
        self.assertLessEqual(max(abs(tank.pos[0] - world.hq.pos[0]), abs(tank.pos[1] - world.hq.pos[1])), 2)
        self.assertIs(world.grid.tile(tank.pos).unit, tank)
        self.assertFalse(world.pick_hero("mage", 1))       # um herói por jogador
        self.assertFalse(world.pick_hero("tank", 2))       # papel já tem dono
        self.assertTrue(world.pick_hero("mage", 2))
        self.assertEqual(world.release_heroes(1), 1)
        self.assertEqual(tank.owner, 0)
        self.assertTrue(world.can_control(tank, 2))         # sem dono: qualquer um comanda
        self.assertTrue(world.pick_hero("tank", 3))         # e pode ser assumido
        self.assertEqual(tank.owner, 3)
        self.assertEqual(len(world.heroes), 2)

    def test_ownership(self):
        world = arena()
        h = hero(world, "ranged", (5, 5), owner=2)
        self.assertTrue(world.can_control(h, 2))
        self.assertFalse(world.can_control(h, 1))
        self.assertTrue(world.can_control(h, None))
        self.assertTrue(world.can_control(Soldier((1, 1)), 1))


class CombatTests(unittest.TestCase):
    def test_armor_reduces_hits_min_one(self):
        world = arena()
        tank = hero(world, "tank", (5, 5))
        self.assertEqual(tank.take_damage(5), 5 - tank.armor)
        self.assertEqual(tank.take_damage(1), 1)

    def test_taunt_pulls_aggro(self):
        world = arena()
        tank = hero(world, "tank", (5, 5))
        soldier = Soldier((7, 5))
        world.grid.place_unit(soldier)
        s = swarm(world, (6, 5), 2)
        self.assertTrue(world.use_skill(tank, "taunt", tank.pos))
        self.assertEqual(s.taunt_hero, "tank")
        tank_hp, soldier_hp = tank.hp, soldier.hp
        world.zombies_move()
        world.zombies_attack()
        self.assertLess(tank.hp, tank_hp)
        self.assertEqual(soldier.hp, soldier_hp)
        world.end_round()
        self.assertEqual(s.taunt_turns, 0)
        self.assertIsNone(s.taunt_hero)

    def test_taunt_draws_far_swarm(self):
        world = arena()
        tank = hero(world, "tank", (5, 5))
        world.grid.place_building(Tent((9, 8)))
        s = swarm(world, (8, 7), 1)  # perto da tenda, a 3 do tanque
        world.use_skill(tank, "taunt", tank.pos)
        before = abs(s.pos[0] - 5) + abs(s.pos[1] - 5)
        world.zombies_move()
        self.assertLess(abs(s.pos[0] - 5) + abs(s.pos[1] - 5), before)

    def test_guard_adds_armor_until_end_of_round(self):
        world = arena()
        tank = hero(world, "tank", (5, 5))
        base = tank.armor
        world.use_skill(tank, "guard", tank.pos)
        self.assertGreater(tank.armor, base)
        world.end_round()
        self.assertEqual(tank.armor, base)

    def test_stealth_ignored_by_zombies_and_broken_by_attack(self):
        world = arena()
        rogue = hero(world, "rogue", (5, 5))
        s = swarm(world, (6, 5), 3)
        world.use_skill(rogue, "stealth", rogue.pos)
        hp = rogue.hp
        world.zombies_move()
        world.zombies_attack()
        self.assertEqual(rogue.hp, hp)
        world.end_round()
        world.begin_player_phase()
        self.assertTrue(rogue.stealthed)
        target = swarm(world, (4, 5), 3)
        self.assertTrue(world.unit_attack(rogue, target.pos))
        self.assertFalse(rogue.stealthed)
        self.assertIsNotNone(s)

    def test_shove_pushes_and_bumps(self):
        world = arena()
        rogue = hero(world, "rogue", (5, 5))
        s = swarm(world, (6, 5), 3)
        self.assertTrue(world.use_skill(rogue, "shove", (6, 5)))
        self.assertEqual(s.pos, (8, 5))
        self.assertEqual(s.count, 3)
        world2 = arena()
        r2 = hero(world2, "rogue", (5, 5))
        s2 = swarm(world2, (6, 5), 3)
        world2.grid.place_building(Tent((7, 5)))
        world2.use_skill(r2, "shove", (6, 5))
        self.assertEqual(s2.pos, (6, 5))
        self.assertEqual(s2.count, 2)  # bateu na tenda: 1 de dano

    def test_lure_emits_noise_at_target(self):
        world = arena()
        rogue = hero(world, "rogue", (5, 5))
        world.use_skill(rogue, "lure", (10, 5))
        self.assertTrue(any(ev.pos == (10, 5) for ev in world.pending_noise))

    def test_pierce_hits_every_swarm_in_line(self):
        world = arena()
        dps = hero(world, "ranged", (5, 5))
        a, b = swarm(world, (5, 7), 3), swarm(world, (5, 9), 3)
        other = swarm(world, (7, 7), 3)
        self.assertIn((5, 6), world.skill_targets(dps, "pierce"))
        self.assertTrue(world.use_skill(dps, "pierce", (5, 6)))
        self.assertFalse(a.alive)
        self.assertFalse(b.alive)
        self.assertTrue(other.alive)
        self.assertGreaterEqual(dps.xp, 6)

    def test_snipe_long_range(self):
        world = arena()
        dps = hero(world, "ranged", (5, 5))
        s = swarm(world, (12, 5), 10)
        self.assertIn((12, 5), world.skill_targets(dps, "snipe"))
        world.use_skill(dps, "snipe", (12, 5))
        self.assertEqual(s.count, 10 - SKILL_SPECS["snipe"].power)

    def test_heals(self):
        world = arena()
        healer = hero(world, "healer", (5, 5))
        soldier = Soldier((6, 5))
        world.grid.place_unit(soldier)
        soldier.hp = 1
        self.assertEqual(world.skill_targets(healer, "heal"), [(6, 5)])
        world.use_skill(healer, "heal", (6, 5))
        self.assertEqual(soldier.hp, 1 + SKILL_SPECS["heal"].power)
        world.begin_player_phase()
        soldier.hp, healer.hp = 1, 1
        self.assertTrue(world.use_skill(healer, "heal_aoe", healer.pos))
        self.assertGreater(soldier.hp, 1)
        self.assertGreater(healer.hp, 1)

    def test_mage_mana_fireball_root_blink(self):
        world = arena()
        mage = hero(world, "mage", (5, 5))
        a, b = swarm(world, (8, 5), 2), swarm(world, (9, 6), 2)
        self.assertTrue(world.use_skill(mage, "fireball", (8, 5)))
        self.assertEqual(mage.mana, HERO_SPECS["mage"].mana - SKILL_SPECS["fireball"].mana)
        self.assertFalse(a.alive)
        self.assertFalse(b.alive)
        mana = mage.mana
        world.begin_player_phase()
        self.assertEqual(mage.mana, min(mage.max_mana, mana + HERO_SPECS["mage"].mana_regen))
        c = swarm(world, (8, 5), 3)
        self.assertTrue(world.use_skill(mage, "root", (8, 5)))
        start = c.pos
        world.zombies_move()
        self.assertEqual(c.pos, start)
        world.begin_player_phase()
        mage.mana = 0
        self.assertFalse(world.use_skill(mage, "blink", (5, 8)))     # sem mana
        mage.mana = 5
        self.assertTrue(world.use_skill(mage, "blink", (5, 8)))
        self.assertEqual(mage.pos, (5, 8))
        self.assertTrue(mage.moved)
        self.assertFalse(mage.acted)

    def test_cooldown_and_single_action(self):
        world = arena()
        tank = hero(world, "tank", (5, 5))
        world.use_skill(tank, "taunt", tank.pos)
        self.assertFalse(world.use_skill(tank, "guard", tank.pos))   # já agiu
        world.begin_player_phase()
        self.assertGreater(tank.cooldown("taunt"), 0)
        self.assertEqual(world.skill_targets(tank, "taunt"), [])
        for _ in range(SKILL_SPECS["taunt"].cooldown):
            world.begin_player_phase()
        self.assertTrue(world.skill_status(tank, "taunt")[0])

    def test_skill_can_be_undone(self):
        world = arena()
        mage = hero(world, "mage", (5, 5))
        swarm(world, (8, 5), 3)
        ap, mana = world.ap, mage.mana
        world.use_skill(mage, "root", (8, 5))
        self.assertTrue(world.undo())
        restored = world.hero("mage")
        self.assertEqual((world.ap, restored.mana, restored.acted), (ap, mana, False))

    def test_ownership_checked_by_commands(self):
        session = Session(GameSetup(11, False))
        session.submit({"op": "hero", "role": "rogue"})
        rogue = session.world.hero_of(1)
        self.assertIsNotNone(rogue)
        session.player_id = 2
        target = next(iter(session.world.unit_moves(rogue)))
        session.submit({"op": "move", "from": list(rogue.pos), "to": list(target)})
        self.assertFalse(rogue.moved)
        session.submit({"op": "release", "player": 1})
        session.submit({"op": "move", "from": list(rogue.pos), "to": list(target)})
        self.assertTrue(rogue.moved)


class XpTests(unittest.TestCase):
    def test_level_up(self):
        world = arena()
        tank = hero(world, "tank", (5, 5))
        hp = tank.max_hp
        dmg = tank.damage
        world.gain_xp(tank, HERO_LEVEL_XP[1])
        self.assertEqual(tank.level, 2)
        self.assertEqual(tank.max_hp, hp + HERO_SPECS["tank"].hp_per_level)
        self.assertEqual(tank.damage, dmg + HERO_SPECS["tank"].damage_per_level)
        world.gain_xp(tank, 1000)
        self.assertEqual(tank.level, len(HERO_LEVEL_XP))
        self.assertEqual(world.xp_progress(tank)[1], None)

    def test_kills_and_survival_give_xp(self):
        world = arena()
        dps = hero(world, "ranged", (5, 5))
        swarm(world, (7, 5), 1)
        world.unit_attack(dps, (7, 5))
        self.assertEqual(dps.kills, 1)
        xp = dps.xp
        world.end_round()
        self.assertEqual(dps.xp, xp + 1)


class DownedTests(unittest.TestCase):
    def _down(self, world, h):
        s = swarm(world, (h.pos[0] + 1, h.pos[1]), 1)
        h.hp = 1
        h.take_damage(5)
        world._on_destroyed(h, s)
        return s

    def test_downed_then_revived(self):
        world = arena()
        tank = hero(world, "tank", (5, 5))
        self._down(world, tank)
        self.assertEqual(tank.state, "downed")
        self.assertIs(world.grid.tile((5, 5)).unit, tank)        # fica no chão
        self.assertNotEqual(world.civil_field().get((5, 5)), 0)  # zumbis não o perseguem
        world.end_round()
        world.begin_player_phase()
        world.end_round()                                       # 2º turno caído
        world.begin_player_phase()
        self.assertEqual(tank.state, "downed")
        healer = hero(world, "healer", (5, 4), owner=2)
        ap = world.ap
        self.assertEqual(world.revive_targets(healer), [(5, 5)])
        self.assertTrue(world.revive_hero(healer, (5, 5)))
        self.assertEqual(world.ap, ap - HERO_REVIVE_AP)
        self.assertEqual(tank.state, "active")
        self.assertTrue(tank.alive)
        self.assertEqual(tank.hp, round(tank.max_hp * 0.6))      # resgatado pela Médica
        self.assertGreater(healer.xp, 0)

    def test_unit_revives_with_low_hp(self):
        world = arena()
        dps = hero(world, "ranged", (5, 5))
        self._down(world, dps)
        soldier = Soldier((4, 5))
        world.grid.place_unit(soldier)
        world.revive_hero(soldier, (5, 5))
        self.assertEqual(dps.hp, max(1, round(dps.max_hp * 0.3)))
        self.assertTrue(dps.acted and dps.moved)

    def test_captured_then_returns_with_debuff(self):
        world = arena()
        dps = hero(world, "ranged", (5, 5))
        world.gain_xp(dps, HERO_LEVEL_XP[1] + 4)
        xp, level = dps.xp, dps.level
        attacker = self._down(world, dps)
        world.grid.remove_swarm(attacker)
        world.end_round()          # turno da queda (não conta)
        world.end_round()          # 1
        self.assertEqual(dps.state, "downed")
        world.end_round()          # 2 -> capturado
        self.assertEqual(dps.state, "recovering")
        self.assertIsNot(world.grid.tile((5, 5)).unit, dps)
        self.assertLess(dps.xp, xp)
        self.assertEqual(dps.level, level)
        for _ in range(HERO_RECOVERY_TURNS - 1):
            world.end_round()
            self.assertEqual(dps.state, "recovering")
        world.end_round()
        self.assertEqual(dps.state, "active")
        self.assertIs(world.grid.tile(dps.pos).unit, dps)
        self.assertLessEqual(max(abs(dps.pos[0] - world.hq.pos[0]), abs(dps.pos[1] - world.hq.pos[1])), 1)
        self.assertEqual(dps.debuff_turns, HERO_DEBUFF_TURNS)
        self.assertEqual(dps.damage, HERO_SPECS["ranged"].damage + HERO_SPECS["ranged"].damage_per_level - 1)
        self.assertLess(dps.hp, dps.max_hp)

    def test_zombies_do_not_grow_from_downed_hero(self):
        world = arena()
        tank = hero(world, "tank", (5, 5))
        tank.hp = 1
        s = swarm(world, (6, 5), 2)
        world.zombies_attack()
        self.assertEqual(tank.state, "downed")
        self.assertEqual(s.count, 2)


class HeroDeterminismTests(unittest.TestCase):
    def test_replay_with_heroes(self):
        session = Session(GameSetup(21, True))
        session.submit({"op": "hero", "role": "mage"})
        mage = session.world.hero_of(1)
        dest = sorted(session.world.unit_moves(mage))[0]
        session.submit({"op": "move", "from": list(mage.pos), "to": list(dest)})
        session.submit({"op": "end_turn"})
        session.turns.resolve_instantly()
        session.submit({"op": "skill", "skill": "blink", "from": list(mage.pos),
                        "to": list(sorted(session.world.skill_targets(mage, "blink"))[0])})
        session.submit({"op": "end_turn"})
        session.turns.resolve_instantly()
        replay = Session(GameSetup(21, True))
        replay.start(session.setup, session.log)
        self.assertEqual(world_checksum(replay.world), world_checksum(session.world))


if __name__ == "__main__":
    unittest.main()
