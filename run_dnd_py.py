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


def _load_fonts(dir_path: str):
    """Register bundled Noto Sans fonts with Windows before any tkinter window opens."""
    if sys.platform != 'win32':
        return
    import ctypes
    _FR_PRIVATE = 0x10
    fonts_dir = os.path.join(dir_path, 'Assets', 'Fonts')
    for fname in ('NotoSans-Regular.ttf', 'NotoSans-Bold.ttf'):
        path = os.path.join(fonts_dir, fname)
        if os.path.isfile(path):
            ctypes.windll.gdi32.AddFontResourceExW(path, _FR_PRIVATE, 0)


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


def _run_launcher() -> argparse.Namespace | None:
    """Show the startup mode-selection dialog. Returns a populated Namespace or None if cancelled."""
    import PySimpleGUI as sg

    _prev_theme = sg.theme()
    sg.theme("DarkGrey13")

    dm_fields = [
        [sg.Text("Password:", size=(12, 1)),
         sg.Input('', key='-DM_PASS-', password_char='*', size=(24, 1))],
        [sg.Text("Leave blank to allow anyone to join.", font=("Arial", 9),
                 text_color='gray', pad=(0, (0, 4)))],
    ]
    player_fields = [
        [sg.Text("Your name:", size=(12, 1)),
         sg.Input('', key='-NAME-', size=(24, 1))],
        [sg.Text("DM address:", size=(12, 1)),
         sg.Input('', key='-HOST-', size=(24, 1))],
        [sg.Text("Color:", size=(12, 1)),
         sg.Combo(_PLAYER_COLORS, default_value=random.choice(_PLAYER_COLORS),
                  key='-COLOR-', size=(22, 1), readonly=True)],
        [sg.Checkbox("Skip TLS verification", key='-INSECURE-', default=True,
                     pad=(0, (4, 0)))],
    ]

    layout = [
        [sg.Text("DungeonPy", font=("Arial", 16, "bold"), pad=(0, (0, 8)))],
        [sg.HorizontalSeparator()],
        [sg.Radio("Dungeon Master", "MODE", key='-MODE_DM-',
                  default=True, enable_events=True, pad=(0, (10, 2)))],
        [sg.Radio("Player", "MODE", key='-MODE_PLAYER-',
                  enable_events=True, pad=(0, (2, 10)))],
        [sg.HorizontalSeparator()],
        [sg.Column(dm_fields,     key='-DM_COL-',     visible=True,  pad=(0, (8, 0)))],
        [sg.Column(player_fields, key='-PLAYER_COL-', visible=False, pad=(0, (8, 0)))],
        [sg.HorizontalSeparator()],
        [sg.Push(),
         sg.Button("Launch", size=(10, 1), bind_return_key=True),
         sg.Button("Quit",   size=(10, 1)),
         sg.Push()],
    ]

    window = sg.Window("DungeonPy", layout, margins=(28, 20), finalize=True)

    while True:
        event, values = window.read()

        if event in (sg.WIN_CLOSED, "Quit"):
            window.close()
            return None

        if event == '-MODE_DM-':
            window['-DM_COL-'].update(visible=True)
            window['-PLAYER_COL-'].update(visible=False)

        elif event == '-MODE_PLAYER-':
            window['-DM_COL-'].update(visible=False)
            window['-PLAYER_COL-'].update(visible=True)

        elif event == "Launch":
            if values['-MODE_PLAYER-']:
                name = values['-NAME-'].strip()
                host = values['-HOST-'].strip()
                if not name or not host:
                    sg.popup_error("Name and DM address are required.", title="DungeonPy")
                    continue
            break

    window.close()
    sg.theme(_prev_theme)

    args = argparse.Namespace(
        dir=_DEFAULT_DIR,
        verbose=False,
        super_verbose=False,
        port=8765,
        cert=None,
        key=None,
    )

    if values['-MODE_DM-']:
        args.mode     = 'dm'
        args.host     = None
        args.password = values['-DM_PASS-'].strip() or None
        args.name     = None
        args.color    = 'white'
        args.insecure = False
    else:
        args.mode     = 'player'
        args.name     = values['-NAME-'].strip()
        args.host     = values['-HOST-'].strip()
        args.color    = values['-COLOR-']
        args.insecure = values['-INSECURE-']
        args.password = None

    return args


def main():
    # Hidden picker mode — must be checked before argparse so unknown flags don't abort.
    if len(sys.argv) >= 2 and sys.argv[1] == "--_picker":
        _run_picker_mode(sys.argv[2:])
        return

    # No arguments → show the graphical launcher.
    if len(sys.argv) == 1:
        _load_fonts(_DEFAULT_DIR)
        args = _run_launcher()
        if args is None:
            return
    else:
        parser = argparse.ArgumentParser(description="Run the D&D Map and Tracker system.")
        parser.add_argument(
            "--mode",
            choices=["dm", "player"],
            default="dm",
            help="dm: host a session.  player: connect to a DM's server.",
        )
        parser.add_argument("--dir", type=str, default=_DEFAULT_DIR,
                            help="Base directory for maps, data, and textures.")
        parser.add_argument("--verbose", action="store_true",
                            help="Enable verbose logging.")
        parser.add_argument("--super_verbose", action="store_true",
                            help="Enable extra-verbose logging.")
        parser.add_argument("--host", type=str, default=None,
                            help="DM's IP address (--mode player).")
        parser.add_argument("--port", type=int, default=8765,
                            help="WebSocket port (default: 8765).")
        parser.add_argument("--name", type=str, default=None,
                            help="Your character name (--mode player).")
        parser.add_argument("--color", type=str, default=None,
                            choices=_PLAYER_COLORS,
                            help=f"Token highlight color. Choices: {', '.join(_PLAYER_COLORS)}.")
        parser.add_argument("--password", type=str, default=None,
                            help="DM session password (--mode dm). Prompted if omitted.")
        parser.add_argument("--insecure", action="store_true",
                            help="Skip TLS certificate verification (--mode player).")
        parser.add_argument("--cert", type=str, default=None,
                            help="Path to TLS certificate (--mode dm).")
        parser.add_argument("--key", type=str, default=None,
                            help="Path to TLS private key (--mode dm).")

        args = parser.parse_args()
        _load_fonts(args.dir)

        # DM: prompt for password if not provided on the command line.
        if args.mode == "dm" and args.password is None:
            args.password = getpass.getpass("[DungeonPy] DM password (leave blank to disable): ")
            if not args.password:
                args.password = None

        # Player: show connection dialog if --name or --host are missing.
        if args.mode == "player" and (not args.name or not args.host):
            import PySimpleGUI as sg
            sg.theme("DarkGrey13")
            layout = [
                [sg.Text("DungeonPy — Connect", font=("Arial", 14, "bold"), pad=(0, (0, 12)))],
                [sg.Text("Your name:", size=(10, 1)),
                 sg.Input(args.name or "", key="-NAME-", size=(28, 1))],
                [sg.Text("DM address:", size=(10, 1)),
                 sg.Input(args.host or "", key="-HOST-", size=(28, 1))],
                [sg.Text("Color:", size=(10, 1)),
                 sg.Combo(_PLAYER_COLORS,
                          default_value=args.color or random.choice(_PLAYER_COLORS),
                          key="-COLOR-", size=(26, 1), readonly=True)],
                [sg.Checkbox("Skip TLS verification", key="-INSECURE-",
                             default=args.insecure, pad=(0, (8, 0)))],
                [sg.Push(),
                 sg.Button("Connect", size=(10, 1), bind_return_key=True),
                 sg.Button("Cancel",  size=(10, 1)),
                 sg.Push()],
            ]
            window = sg.Window("DungeonPy", layout, margins=(24, 20), finalize=True)
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

        if args.mode == "player" and not args.color:
            args.color = random.choice(_PLAYER_COLORS)

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
