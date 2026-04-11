import argparse
import getpass
import os
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

# When frozen by PyInstaller, default the asset directory to wherever the
# executable lives so Assets/, Maps/ etc. are found next to the binary.
if getattr(sys, 'frozen', False):
    _DEFAULT_DIR = os.path.dirname(sys.executable) + os.sep
else:
    _DEFAULT_DIR = "./"

_PLAYER_COLORS = [
    "red", "blue", "green", "purple",
    "cyan", "pink", "white",
]


def _run_picker_mode(argv):
    """Hidden subcommand used by the frozen binary to host tkinter picker dialogs.
    The map_manager spawns `<exe> --_picker object <dir>` or `<exe> --_picker light`
    so that tkinter runs in a clean process without conflicting with pygame's SDL."""
    import tkinter as tk
    from tkinter import filedialog, simpledialog

    if not argv:
        return
    kind = argv[0]

    if kind == "object":
        objects_dir = argv[1] if len(argv) > 1 else "."
        root = tk.Tk()
        root.withdraw()
        root.lift()
        path = filedialog.askopenfilename(
            title="Select object icon",
            initialdir=objects_dir if os.path.isdir(objects_dir) else ".",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif"), ("All files", "*.*")],
        )
        if not path:
            root.destroy()
            return
        w = simpledialog.askinteger("Object width",  "Width in tiles?",
                                    initialvalue=1, minvalue=1, maxvalue=20, parent=root)
        h = simpledialog.askinteger("Object height", "Height in tiles?",
                                    initialvalue=1, minvalue=1, maxvalue=20, parent=root)
        root.destroy()
        print(os.path.basename(path))
        print(w or 1)
        print(h or 1)

    elif kind == "light":
        root = tk.Tk()
        root.withdraw()
        root.lift()
        r = simpledialog.askinteger("Light radius", "Radius in tiles?",
                                    initialvalue=4, minvalue=1, maxvalue=20, parent=root)
        if not r:
            root.destroy()
            return
        dlg = tk.Toplevel(root)
        dlg.title("Light settings")
        dlg.resizable(False, False)
        tk.Label(dlg, text="Color:").pack(padx=10, pady=(10, 2))
        color_var = tk.StringVar(value="warm")
        for c in ("warm", "cool", "white", "red", "green", "blue", "black"):
            tk.Radiobutton(dlg, text=c, variable=color_var, value=c).pack(anchor="w", padx=20)
        tk.Label(dlg, text="Intensity:").pack(padx=10, pady=(8, 2))
        alpha_var = tk.IntVar(value=60)
        tk.Scale(dlg, from_=0, to=255, orient="horizontal",
                 variable=alpha_var, length=180).pack(padx=10)
        tk.Button(dlg, text="OK", command=dlg.destroy).pack(pady=8)
        dlg.grab_set()
        root.wait_window(dlg)
        root.destroy()
        print(r)
        print(color_var.get())
        print(alpha_var.get())


def main():
    # Hidden picker mode — must be checked before argparse so unknown flags don't abort.
    if len(sys.argv) >= 2 and sys.argv[1] == "--_picker":
        _run_picker_mode(sys.argv[2:])
        return

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
    parser.add_argument("--dir", type=str, default=_DEFAULT_DIR,
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

    # Player mode: show a connection dialog if --name or --host are missing
    if args.mode == "player" and (not args.name or not args.host):
        import PySimpleGUI as sg
        _prev_theme = sg.theme()
        sg.theme("DarkGrey13")
        layout = [
            [sg.Text("DungeonPy — Connect", font=("Arial", 14, "bold"), pad=(0, (0, 12)))],
            [sg.Text("Your name:", size=(10, 1)),
             sg.Input(args.name or "", key="-NAME-", size=(28, 1), focus=True)],
            [sg.Text("DM address:", size=(10, 1)),
             sg.Input(args.host or "", key="-HOST-", size=(28, 1))],
            [sg.Text("Color:", size=(10, 1)),
             sg.Combo(_PLAYER_COLORS, default_value=args.color or random.choice(_PLAYER_COLORS),
                      key="-COLOR-", size=(26, 1), readonly=True)],
            [sg.Checkbox("Skip TLS verification (insecure)", key="-INSECURE-",
                         default=args.insecure, pad=(0, (8, 0)))],
            [sg.Push(),
             sg.Button("Connect", size=(10, 1), bind_return_key=True),
             sg.Button("Cancel",  size=(10, 1)),
             sg.Push()],
        ]
        window = sg.Window("DungeonPy", layout, margins=(24, 20), finalize=True)
        window["-NAME-"].set_focus()
        event, values = window.read()
        window.close()
        if event in (sg.WIN_CLOSED, "Cancel"):
            sys.exit(0)
        args.name     = values["-NAME-"].strip()
        args.host     = values["-HOST-"].strip()
        args.color    = values["-COLOR-"]
        args.insecure = values["-INSECURE-"]
        if not args.name or not args.host:
            sg.popup_error("Name and DM address are required.", title="DungeonPy")
            sys.exit(1)
        sg.theme(_prev_theme)  # restore default theme for the chat window

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
