import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

from game.config import IMAGES_DIR, SPRITE_FILES
from game.renderer import swarm_sprite_key
from game.sprites import SpriteManager


class SpriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    def test_missing_folder_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            sm = SpriteManager(Path(tmp) / "nope")
            self.assertIsNone(sm.get("ranger", 32))
            self.assertFalse(sm.has("ranger"))
            self.assertIsNone(sm.get("chave_inexistente", 32))

    def test_scaled_to_square_tile_and_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = pygame.Surface((30, 60), pygame.SRCALPHA)
            img.fill((200, 100, 50, 255))
            pygame.image.save(img, os.path.join(tmp, "x.png"))
            sm = SpriteManager(Path(tmp), {"x": ("x.png", 0.0)})
            a = sm.get("x", 32)
            self.assertEqual(a.get_size(), (32, 32))
            self.assertIs(a, sm.get("x", 32))
            dark = sm.get("x", 32, (128, 128, 128))
            self.assertLess(dark.get_at((5, 5)).r, a.get_at((5, 5)).r)

    @unittest.skipUnless(IMAGES_DIR.is_dir(), "assets/images ausente")
    def test_project_assets_load(self):
        sm = SpriteManager()
        for key in SPRITE_FILES:
            self.assertEqual(sm.get(key, 48).get_size(), (48, 48), key)
        self.assertEqual(sm.errors, [])

    def test_swarm_sprite_by_type(self):
        for kind in ("walker", "runner", "brute", "harpy", "venom"):
            self.assertIn(swarm_sprite_key(kind), SPRITE_FILES)


if __name__ == "__main__":
    unittest.main()
