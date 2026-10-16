"""Ponto de entrada: python main.py [--seed N]"""
from __future__ import annotations

import argparse

from game.app import GameApp


def main() -> None:
    parser = argparse.ArgumentParser(description="They Are Thousands - protótipo tático")
    parser.add_argument("--seed", type=int, default=None, help="semente do mapa (determinístico)")
    parser.add_argument("--no-fog", action="store_true", help="inicia com a névoa de guerra desligada")
    parser.add_argument("--frames", type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    GameApp(seed=args.seed, fog_enabled=not args.no_fog).run(max_frames=args.frames)


if __name__ == "__main__":
    main()
