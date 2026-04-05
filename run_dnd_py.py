import argparse
import getpass
import random
import sys

# On Windows, tkinter (used by PySimpleGUI) is DPI-unaware by default and gets
# scaled up by the OS, making fonts and emoji huge on high-DPI displays.
# Declaring DPI awareness before any GUI import prevents this.
if sys.platform == 'win32':
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

from Core.game import Game

_PLAYER_COLORS = [
    "red", "blue", "green", "purple",
    "cyan", "pink", "white",
]


def main():
    parser = argparse.ArgumentParser(description="Run the D&D Map and Tracker system.")
    parser.add_argument(
        "--mode",
        choices=["map", "tracker", "both", "dm", "player"],
        default="both",
        help=(
            "both/map/tracker: local play (no networking). "
            "dm: host a multiplayer session (requires --password). "
            "player: connect to a DM's server (requires --host and --name)."
        ),
    )
    parser.add_argument("--dir", type=str, default="./",
                        help="Base directory for maps, data, and textures.")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable verbose logging.")
    parser.add_argument("--super_verbose", action="store_true",
                        help="Enable extra-verbose logging.")

    # Networking
    parser.add_argument("--host", type=str, default=None,
                        help="Server bind address for --mode dm (default: 0.0.0.0), or DM's IP address for --mode player (required).")
    parser.add_argument("--port", type=int, default=8765,
                        help="WebSocket port (default: 8765).")
    parser.add_argument("--name", type=str, default=None,
                        help="Your combatant name (required for --mode player).")
    parser.add_argument("--color", type=str, default=None,
                        choices=_PLAYER_COLORS,
                        help=f"Your selection highlight color for --mode player. "
                             f"Choices: {', '.join(_PLAYER_COLORS)}. Random if omitted.")
    parser.add_argument("--password", type=str, default=None,
                        help="DM password (--mode dm). Prompted if omitted.")
    parser.add_argument("--insecure", action="store_true",
                        help="Skip TLS certificate verification (--mode player, self-signed certs).")
    parser.add_argument("--cert", type=str, default=None,
                        help="Path to TLS certificate file (--mode dm, overrides auto-generated).")
    parser.add_argument("--key", type=str, default=None,
                        help="Path to TLS private key file (--mode dm, overrides auto-generated).")

    args = parser.parse_args()

    # DM mode: prompt for password if not provided
    if args.mode == "dm" and args.password is None:
        args.password = getpass.getpass("[DungeonPy] DM password (leave blank to disable): ")
        if not args.password:
            args.password = None
            print("[DungeonPy] Warning: running without a DM password — anyone can claim DM role.")

    # Player mode: --name and --host are required; assign random color if omitted
    if args.mode == "player" and not args.name:
        parser.error("--mode player requires --name <your combatant name>")
    if args.mode == "player" and not args.host:
        parser.error("--mode player requires --host <DM's IP address>")
    if args.mode == "player" and not args.color:
        args.color = random.choice(_PLAYER_COLORS)
        print(f"[DungeonPy] No color specified — assigned '{args.color}'.")

    game = Game(
        dir_path=args.dir,
        mode=args.mode,
        verbose=args.verbose,
        super_verbose=args.super_verbose,
        host=args.host,
        port=args.port,
        player_name=args.name,
        player_color=args.color or 'white',
        password=args.password,
        insecure=args.insecure,
        cert=args.cert,
        key=args.key,
    )
    game.run()


if __name__ == "__main__":
    main()
