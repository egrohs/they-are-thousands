import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from game.audio import MusicPlayer


class MusicPlayerTests(unittest.TestCase):
    def setUp(self):
        pygame.init()

    def tearDown(self):
        pygame.quit()

    def test_missing_folder_is_graceful(self):
        player = MusicPlayer(Path("pasta/que/nao/existe"))
        self.assertEqual(player.tracks, [])
        self.assertFalse(player.can_play)
        player.start()
        player.toggle()
        player.next_track()
        self.assertIsNotNone(player.error)

    def test_lists_only_audio_files_sorted(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("b.ogg", "A.mp3", "notes.txt", "c.wav"):
                Path(d, name).write_bytes(b"")
            player = MusicPlayer(Path(d), enabled=False)
            self.assertEqual([t.name for t in player.tracks], ["A.mp3", "b.ogg", "c.wav"])

    def test_corrupt_tracks_do_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "ruim.mp3").write_bytes(b"not audio")
            player = MusicPlayer(Path(d))
            player.start()
            self.assertIsNotNone(player.error)

    def test_volume_is_clamped(self):
        player = MusicPlayer(Path("inexistente"), volume=0.95)
        player.change_volume(0.2)
        self.assertEqual(player.volume, 1.0)
        player.change_volume(-5)
        self.assertEqual(player.volume, 0.0)


if __name__ == "__main__":
    unittest.main()
