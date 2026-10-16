"""Ponto de entrada: python main.py [--seed N] [--map arquivo.json] [--editor]
                                    [--host [PORTA] | --join IP[:PORTA]]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from game.app import GameApp
    from game.config import NET_PORT
    from game.maps import MapError, load_map
except ValueError as exc:  # StatsError: CSV de balanceamento inválido em data/
    if type(exc).__name__ != "StatsError":
        raise
    sys.exit(f"Erro nos dados de balanceamento (data/*.csv):\n  {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="They Are Thousands - protótipo tático")
    parser.add_argument("--seed", type=int, default=None, help="semente do mapa (determinístico)")
    parser.add_argument("--no-fog", action="store_true", help="inicia com a névoa de guerra desligada")
    parser.add_argument("--no-music", action="store_true", help="inicia com a trilha sonora desligada")
    parser.add_argument("--map", type=str, default=None, help="arquivo .json de mapa personalizado")
    parser.add_argument("--editor", action="store_true", help="abre direto no editor de mapas")
    net = parser.add_mutually_exclusive_group()
    net.add_argument("--host", type=int, nargs="?", const=NET_PORT, default=None, metavar="PORTA",
                     help=f"hospeda uma partida co-op (porta padrão {NET_PORT})")
    net.add_argument("--join", type=str, default=None, metavar="IP[:PORTA]",
                     help="entra na partida co-op de um anfitrião")
    parser.add_argument("--frames", type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    map_data = None
    if args.map:
        try:
            map_data = load_map(Path(args.map))
        except MapError as exc:
            parser.error(str(exc))
    app = GameApp(seed=args.seed, fog_enabled=not args.no_fog, music_enabled=not args.no_music,
                  map_data=map_data, start_in_editor=args.editor)
    if args.host is not None and not app.start_host(args.host):
        parser.exit(1, f"Co-op: {app.settings.net_error}\n")
    if args.join is not None and not app.join(args.join):
        parser.exit(1, f"Co-op: {app.settings.net_error}\n")
    app.run(max_frames=args.frames)


if __name__ == "__main__":
    main()
