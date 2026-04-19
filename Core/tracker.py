"""
tracker.py — DM-side combat tracker UI for DungeonPy.

Runs a PySimpleGUI initiative table in a daemon thread (in ``both``/``dm``
mode the map occupies the main thread).  The tracker displays combatants
sorted by initiative, lets the DM manage HP, conditions, and turns, and
communicates changes to the MapManager via the GameServer event bus.

Key interactions
----------------
- Token selected on map  → ``handle_server_event`` highlights the matching row.
- Turn advanced in tracker → server emits ``turn_advanced`` → map applies blue glow.
- Combatant added/edited  → server emits ``combatant_updated`` → map redraws token.
- ``_squelch_table_event`` prevents feedback loops when the map triggers a row change.
"""

from datetime import datetime
import io
import os
import sys
import tkinter as tk
import PySimpleGUI as sg
from Core.combatant import Combatant
from Core.log_utils import log_msg
from Core.chat_window import ChatWindow

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

_UI_FONT = 'Noto Sans' if sys.platform == 'win32' else 'gothic'

CONDITION_ICON_SIZE = 36 # pixels

_COND_ABBREV = {
    'Blind': 'Bln', 'Charmed': 'Chr', 'Deaf': 'Def', 'Frightened': 'Frt',
    'Grappled': 'Grp', 'Incapacitated': 'Inc', 'Invisible': 'Inv', 'Paralyzed': 'Par',
    'Petrified': 'Pet', 'Poisoned': 'Poi', 'Prone': 'Prn', 'Restrained': 'Rst',
    'See-invisible': 'SeI', 'Stunned': 'Stn', 'Unconscious': 'Unc', 'Dead': 'Ded',
}



class Tracker:
    """PySimpleGUI combat tracker window.

    Manages the combatant list, HP, conditions, and turn order.  Sends intents
    to the GameServer via ``_submit`` and reacts to server events delivered
    through ``handle_server_event()``.

    Args:
        server: The shared ``GameServer`` instance (used to read current state).
        submit: Callable ``(intent: dict) → None`` used to send all mutations.
            Defaults to ``server.submit`` if not provided.
        dir_path: Base directory for asset resolution (icons, condition images).
        verbose: Enable timestamped logging.
        super_verbose: Enable per-combatant comparison logs.
    """

    def __init__(self, server, submit=None, dir_path='', verbose=False, super_verbose=False):
        self.server = server
        self._submit = submit if submit is not None else server.submit
        self.dir_path = dir_path
        self.verbose = verbose
        self.super_verbose = super_verbose
        self._squelch_table_event = 0   # counter: suppress this many upcoming TABLE events
        self._selected_index = None
        self._pending_timers = {}   # condition → expiry turn, set during the current edit session
        self._connected_players: dict[str, dict] = {}  # name → {"select": bool, "move": bool, "color": str}
        self._known_players: dict[str, str] = {}       # name → color; persists across disconnects
        self._map_path: str | None = None
        self._map_visible: bool = False
        self._chat: ChatWindow | None = None
        self.window = None

        self.condition_list = [
            'Blind', 'Charmed', 'Deaf', 'Frightened', 'Grappled', 'Hidden',
            'Incapacitated', 'Invisible', 'Paralyzed', 'Petrified', 'Poisoned',
            'Prone', 'Restrained', 'See-invisible', 'Stunned', 'Unconscious', 'Dead',
        ]

        # Load condition images from Assets/Conditions/.
        self.condition_images = self._load_condition_images()
        self._table_photos = {}   # keeps ImageTk.PhotoImage refs alive (tkinter GC guard)

        if self.verbose:
            log_msg("[Tracker] Tracker module loaded.")

    # ------------------------------------------------------------------
    # Condition image loading
    # ------------------------------------------------------------------

    def _load_condition_images(self) -> dict:
        """Return {condition_name: png_bytes} for each condition found in Assets/Conditions/."""
        images = {}
        for cond in self.condition_list:
            png_path = os.path.join(self.dir_path, 'Assets', 'Conditions', f'{cond}.png')
            if not os.path.isfile(png_path):
                continue
            with open(png_path, 'rb') as f:
                raw = f.read()
            if _PIL_OK:
                img = Image.open(io.BytesIO(raw)).convert("RGBA")
                img = img.resize((CONDITION_ICON_SIZE, CONDITION_ICON_SIZE), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                images[cond] = buf.getvalue()
            else:
                images[cond] = raw
        return images

    # ------------------------------------------------------------------
    # Server event handling (pub/sub)
    # ------------------------------------------------------------------

    def handle_server_event(self, event: dict):
        """Called by the server on any thread — posts to the GUI event queue."""
        if self.window:
            self.window.write_event_value('SERVER_EVENT', event)

    def _apply_server_event(self, event: dict):
        """Handle a server event on the GUI thread."""
        if event.get("type") == "snapshot":
            # Validate that _selected_index is still in range (e.g. after load_map strips NPCs)
            if self._selected_index is not None and self._selected_index >= len(self.server.combatants):
                self._selected_index = None
                self._clear_form()
            self.window['-TURN-'].update(str(self.server.turn))
            self.refresh_table(self._selected_index)
            state = event.get("state", {})
            self._sync_map_ui(state.get("map_path"), state.get("map_visible", False))
            self._rebuild_chat_tabs()
            return

        action = event.get("action")

        if action == "combatant_updated":
            self.refresh_table(self._selected_index)

        elif action == "combatant_added":
            self.refresh_table(self._selected_index)

        elif action == "combatant_removed":
            self._selected_index = None
            self.refresh_table()

        elif action == "turn_advanced":
            self.window['-TURN-'].update(str(event["turn"]))
            self.refresh_table()

        elif action == "selection_changed" and "selector" not in event:
            name = event["name"]
            for i, c in enumerate(self.server.combatants):
                if c.name == name:
                    # Only highlight the row if selection actually moved (avoids echo from our own click)
                    if i != self._selected_index:
                        self._selected_index = i
                        self._squelch_table_event = 1
                        self.window['-TABLE-'].update(select_rows=[i + 1])
                    self.window['-NAME-'].update(c.name)
                    self.window['-INITIATIVE-'].update(c.initiative)
                    self.window['-HP-'].update('' if c.hp is None else c.hp)
                    self.window['-MAX_HP-'].update('' if c.max_hp is None else c.max_hp)
                    self.window['-IS_PC-'].update(c.is_pc)
                    self.window['-SIZE-'].update(c.size)
                    for cond in self.condition_list:
                        self.window[f'-COND_{cond}-'].update(cond in c.conditions)
                    self.window.refresh()
                    break

        elif action == "selection_cleared" and "selector" not in event:
            if self._selected_index is not None:
                self._selected_index = None
                self._squelch_table_event = 1
                self.window['-TABLE-'].update(select_rows=[])
            self._clear_form()

        elif action == "player_connected":
            color = event.get("color", "white")
            self._connected_players[event["name"]] = {
                "select": False, "move": False, "color": color,
            }
            self._known_players[event["name"]] = color
            self._refresh_players_table()
            self.refresh_table(self._selected_index)

        elif action == "player_disconnected":
            self._connected_players.pop(event["name"], None)
            self._refresh_players_table()
            self.refresh_table(self._selected_index)

        elif action == "player_lock_changed":
            name = event["name"]
            if name in self._connected_players:
                lock_type = event.get("lock_type", "move")
                self._connected_players[name][lock_type] = event["locked"]
                self._refresh_players_table()

        elif action == "map_loaded":
            self._sync_map_ui(event.get("path"), True)

        elif action == "map_visibility_changed":
            self._sync_map_ui(self._map_path, event.get("visible", False))

        elif action in ("combatant_added", "combatant_removed", "combatant_updated"):
            self._rebuild_chat_tabs()

        elif action == "chat_message":
            sender  = event.get("from", "DM")
            to_name = event.get("to")
            text    = event.get("text", "")
            # Determine which PC tab to post to
            pc_name = to_name if to_name else sender
            if self._chat:
                self._chat.receive(pc_name, sender, text)
            if sender != "DM":
                try:
                    self.window['-CHAT_NOTIFY-'].update('● new message')
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_players_table(self):
        rows = [
            [name,
             "✓" if state["select"] else "✗",
             "✓" if state["move"] else "✗"]
            for name, state in self._connected_players.items()
        ]
        self.window['-PLAYERS-'].update(values=rows)

    def _sync_map_ui(self, map_path, map_visible):
        """Keep internal map state and Toggle Map button in sync."""
        self._map_path = map_path
        self._map_visible = map_visible
        has_map = bool(map_path)
        self.window['Toggle Map'].update(disabled=not has_map)
        if has_map:
            self.window['Toggle Map'].update(text='Hide Map' if map_visible else 'Show Map')

    def _pc_names(self) -> list[str]:
        return [c.name for c in self.server.combatants if c.is_pc]

    def _rebuild_chat_tabs(self):
        """Rebuild chat tabs if the PC roster has changed."""
        if self._chat and self._chat.is_open():
            if self._pc_names() != self._chat._pc_names:
                self._chat.rebuild(self._pc_names())

    def _clear_form(self):
        self.window['-NAME-'].update('')
        self.window['-INITIATIVE-'].update('')
        self.window['-HP-'].update('')
        self.window['-MAX_HP-'].update('')
        self.window['-IS_PC-'].update(False)
        self.window['-SIZE-'].update('1')
        for cond in self.condition_list:
            self.window[f'-COND_{cond}-'].update(False)
        self._pending_timers = {}
        self.window.refresh()

    def _start_notes_edit(self, event):
        """Open an inline Entry widget over the Notes cell on double-click."""
        tree = self.window['-TABLE-'].Widget
        if tree.identify_region(event.x, event.y) != 'cell':
            return
        if tree.identify_column(event.x) != '#4':  # Notes is the 4th data column
            return
        item = tree.identify_row(event.y)
        if not item:
            return
        children = list(tree.get_children())
        idx = children.index(item)
        if idx == 0:  # blank deselection row
            return
        combatant = self.server.combatants[idx - 1]

        bbox = tree.bbox(item, '#4')
        if not bbox:
            return
        x, y, w, h = bbox

        var = tk.StringVar(value=combatant.notes or '')
        entry = tk.Entry(tree, textvariable=var)
        entry.place(x=x, y=y, width=w, height=h)
        entry.select_range(0, 'end')
        entry.focus()

        def commit(e=None):
            new_val = var.get()
            entry.destroy()
            self._submit({"action": "update_combatant", "name": combatant.name,
                          "fields": {"notes": new_val}})

        entry.bind('<Return>', commit)
        entry.bind('<FocusOut>', commit)
        entry.bind('<Escape>', lambda e: entry.destroy())

    # ------------------------------------------------------------------
    # Table rendering
    # ------------------------------------------------------------------

    def _make_condition_strip(self, conditions: list):
        """Return an ImageTk.PhotoImage strip of condition icons, or None."""
        if not _PIL_OK or not conditions:
            return None
        size, gap = CONDITION_ICON_SIZE, 2
        imgs = []
        for cond in conditions:
            raw = self.condition_images.get(cond)
            if raw:
                imgs.append(Image.open(io.BytesIO(raw)).convert("RGBA").resize((size, size), Image.LANCZOS))
        if not imgs:
            return None
        total_w = len(imgs) * size + (len(imgs) - 1) * gap
        strip = Image.new("RGB", (total_w, size), (255, 255, 255))
        for i, img in enumerate(imgs):
            strip.paste(img, (i * (size + gap), 0), img)
        return ImageTk.PhotoImage(strip)

    def build_gui_layout(self):

        def chunk(lst, size):
            return [lst[i:i + size] for i in range(0, len(lst), size)]

        table_font = (_UI_FONT, 16, 'normal')

        COND_COL_WIDTH = 15  # fixed chars — wide enough for "See-invisible"
        condition_rows = []
        for row_conds in chunk(self.condition_list, 5):
            row_elements = []
            for cond in row_conds:
                img_data = self.condition_images.get(cond)
                if img_data:
                    row_elements.append(sg.Image(data=img_data))
                row_elements.append(sg.Checkbox(cond, key=f'-COND_{cond}-', font=table_font,
                                                size=(COND_COL_WIDTH, 1), enable_events=True))
            condition_rows.append(row_elements)

        layout = [
            [sg.Text('Initiative Tracker', font=table_font)],
            [sg.Table(values=[], headings=['Name', 'Initiative', 'HP', 'Notes'],
                      auto_size_columns=False, justification='left', col_widths=[10, 10, 10, 40],
                      key='-TABLE-', enable_events=True, row_height=36, expand_x=True, num_rows=10,
                      background_color='white', text_color='black',
                      font=(table_font[0], table_font[1], 'bold'))],
            [sg.Text('Turn:', font=table_font), sg.Input(str(self.server.turn), key='-TURN-', size=(5, 1)),
             sg.Button('⏮ Prev Char'), sg.Button('⏭ Next Char')],
            [sg.HorizontalSeparator()],
            [sg.Text('Name', size=(10, 1), font=table_font), sg.Input(key='-NAME-', size=(30, 1))],
            [sg.Text('Initiative', size=(10, 1), font=table_font), sg.Input(key='-INITIATIVE-', size=(5, 1))],
            [sg.Text('HP:', size=(10, 1), font=table_font), sg.Input(key='-HP-', size=(5, 1)),
             sg.Text('Max HP:', font=table_font), sg.Input(key='-MAX_HP-', size=(5, 1)),
             sg.Text('   Change:', font=table_font), sg.Input('0', key='-HP_CHANGE-', size=(5, 1)),
             sg.Button('Wound'), sg.Button('Heal')],
            [sg.Checkbox('Player Character (PC)', key='-IS_PC-', font=table_font, enable_events=False),
             sg.Text('  Size (tiles):', font=table_font),
             sg.Input('1', key='-SIZE-', size=(3, 1))],
            [sg.Text('Conditions:', font=table_font)],
            *condition_rows,
            [
                sg.Button('Add New'), sg.Button('Apply Stats'), sg.Button('Delete Selected'),
                sg.Button('▲ Move Up'), sg.Button('▼ Move Down'),
                sg.Button('💾 Export'), sg.Button('📂 Load')],
            [sg.HorizontalSeparator()],
            [sg.Text('Map:', font=table_font),
             sg.Button('Load Map', key='Load Map'),
             sg.Button('Show Map', key='Toggle Map', disabled=True),
             sg.Text('  Chat:', font=table_font),
             sg.Button('Close Chat', key='Toggle Chat'),
             sg.Text('', key='-CHAT_NOTIFY-', font=table_font, text_color='orange')],
            [sg.Text('Sight radius:', font=table_font),
             sg.Slider(range=(1, 30), default_value=10, orientation='h',
                       size=(20, 15), key='-SIGHT_RADIUS-', enable_events=True,
                       font=table_font),
             sg.Text('tiles', font=table_font)],
            [sg.HorizontalSeparator()],
            [sg.Text('Connected Players', font=(_UI_FONT, 12, 'bold'))],
            [sg.Table(
                values=[],
                headings=['Player', 'Select', 'Move'],
                key='-PLAYERS-',
                enable_events=True,
                select_mode=sg.TABLE_SELECT_MODE_BROWSE,
                col_widths=[14, 7, 7],
                auto_size_columns=False,
                num_rows=4,
                font=(_UI_FONT, 12),
            )],
            [sg.Button('Toggle Selection', key='Toggle Selection'),
             sg.Button('Toggle Movement', key='Toggle Movement')],
        ]
        return layout

    def refresh_table(self, selected_index=None):
        data = [['', '', '', '']]  # blank row for deselection
        row_conditions = [[]]  # parallel list of condition lists per row
        row_names      = ['']   # raw combatant names (no "→ " prefix) for color lookup
        for i, c in enumerate(self.server.combatants):
            name = f"→ {c.name}" if i == self.server.active_index else c.name
            timer_parts = [f"{_COND_ABBREV.get(cond, cond[:3])}:{exp[0]}@{exp[1]}"
                           for cond, exp in sorted(c.condition_timers.items())]
            notes_display = c.notes + (" [" + ", ".join(timer_parts) + "]" if timer_parts else "")
            data.append([name, c.initiative, '' if c.hp is None else c.hp, notes_display])
            row_conditions.append(list(c.conditions))
            row_names.append(c.name)

        if selected_index is not None and 0 <= selected_index < len(self.server.combatants):
            self._squelch_table_event = 2  # update clears then reselects — two TABLE events expected
            self.window['-TABLE-'].update(values=data, select_rows=[selected_index + 1])
        else:
            self._squelch_table_event = 1  # deselect fires one TABLE event
            self.window['-TABLE-'].update(values=data, select_rows=[])

        tree = self.window['-TABLE-'].Widget
        tree.tag_configure('dead', font=(_UI_FONT, 16, 'overstrike'))
        for info in self._connected_players.values():
            c = info.get("color", "white")
            try:
                r, g, b = (v >> 8 for v in tree.winfo_rgb(c))
                dimmed = f'#{(r + 255) // 2:02x}{(g + 255) // 2:02x}{(b + 255) // 2:02x}'
            except Exception:
                dimmed = c
            tree.tag_configure(f'pc_{c}', background=dimmed, foreground='black')
        new_photos = {}
        for item_id, conditions, cname in zip(tree.get_children(), row_conditions, row_names):
            connected = self._connected_players.get(cname)
            color_tag = (f'pc_{connected["color"]}',) if connected else ()
            tags = (('dead',) + color_tag) if 'Dead' in conditions else color_tag
            photo = self._make_condition_strip(conditions)
            tree.item(item_id, text='', image=photo if photo else '', tags=tags)
            if photo:
                new_photos[item_id] = photo
        self._table_photos = new_photos  # replace; old refs released

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_event(self, event, values, dir_path):
        if event == sg.WIN_CLOSED:
            return

        if event == '-TABLE-' and self._squelch_table_event > 0:
            self._squelch_table_event -= 1
            return

        if self.verbose:
            log_msg(f"[Tracker] Event: {event}")

        if event == '-TABLE-':
            try:
                if values['-TABLE-']:
                    row_index = values['-TABLE-'][0]
                    if self.verbose:
                        log_msg(f"[Tracker] Handling row selection: {row_index}")
                    if row_index == 0:
                        self._selected_index = None
                        self._submit({"action": "clear_selection"})
                        self.window['-TABLE-'].update(select_rows=[])
                        self._clear_form()
                    else:
                        self._selected_index = row_index - 1
                        c = self.server.combatants[self._selected_index]
                        if self.verbose:
                            log_msg(f"[Tracker] Selected index = {self._selected_index}, Combatant: {c}")
                        self.window['-NAME-'].update(c.name)
                        self.window['-INITIATIVE-'].update(c.initiative)
                        self.window['-HP-'].update('' if c.hp is None else c.hp)
                        self.window['-MAX_HP-'].update('' if c.max_hp is None else c.max_hp)
                        self.window['-IS_PC-'].update(c.is_pc)
                        self.window['-SIZE-'].update(c.size)
                        for cond in self.condition_list:
                            self.window[f'-COND_{cond}-'].update(cond in c.conditions)
                        self._submit({"action": "select", "name": c.name})
                        self.window.refresh()
            except Exception as e:
                print(f"Selection error: {e}")
                self._selected_index = None
                self._submit({"action": "clear_selection"})

        elif event.startswith('-COND_') and event.endswith('-') and self._selected_index is not None:
            cond = event[6:-1]
            if values.get(event):  # condition turned ON
                sel = self.server.combatants[self._selected_index]
                popup_layout = [
                    [sg.Text(f'Duration for {cond}:')],
                    [sg.Text('Rounds:', size=(18, 1)),
                     sg.Input('', key='-ROUNDS-', size=(5, 1))],
                    [sg.Text('Initiative at expiry:', size=(18, 1)),
                     sg.Input(str(sel.initiative), key='-INIT-', size=(5, 1))],
                    [sg.Text('(leave Rounds blank for permanent)', font=(_UI_FONT, 10))],
                    [sg.Button('OK'), sg.Button('Cancel')],
                ]
                popup = sg.Window('Condition Duration', popup_layout,
                                  keep_on_top=True, modal=True, finalize=True)
                pev, pvals = popup.read()
                popup.close()
                if pev == 'OK' and pvals['-ROUNDS-'].strip():
                    try:
                        n = int(pvals['-ROUNDS-'].strip())
                        init_exp = int(pvals['-INIT-'].strip())
                        if n > 0:
                            self._pending_timers[cond] = [self.server.turn + n, init_exp]
                    except ValueError:
                        pass
                elif pev != 'OK':
                    # User cancelled — revert the checkbox and skip applying anything
                    self.window[f'-COND_{cond}-'].update(False)
                    return
            else:  # condition turned OFF
                self._pending_timers.pop(cond, None)

            # Apply condition change immediately
            c = self.server.combatants[self._selected_index]
            new_conditions = [cd for cd in self.condition_list if values.get(f'-COND_{cd}-')]
            new_timers = {cd: t for cd, t in c.condition_timers.items() if cd in new_conditions}
            new_timers.update(self._pending_timers)
            self._pending_timers = {}
            self._submit({"action": "update_combatant", "name": c.name,
                          "fields": {"conditions": new_conditions, "condition_timers": new_timers}})

        elif event == 'Add New':
            if self._selected_index is not None:
                sg.popup('Cannot add a new combatant while another is selected.')
                return
            else:
                try:
                    name = values['-NAME-'].strip()
                    init_str = values['-INITIATIVE-'].strip()
                    if not name or not init_str:
                        sg.popup('Please enter a name and initiative value.')
                        return
                    init = int(init_str)
                    hp_str = values['-HP-'].strip()
                    hp = int(hp_str) if hp_str else None
                    max_hp_str = values['-MAX_HP-'].strip()
                    max_hp = int(max_hp_str) if max_hp_str else None
                    conditions = [cond for cond in self.condition_list if values.get(f'-COND_{cond}-')]
                    icon_path = sg.popup_get_file(
                        f"Select icon for {name} (close to skip)",
                        initial_folder=os.path.join(dir_path, 'Assets', 'Combatants'),
                        file_types=(("Image Files", "*.png *.jpg *.jpeg"),),
                        no_window=False,
                    )
                    icon = os.path.basename(icon_path) if icon_path else None
                    size_str = values.get('-SIZE-', '1').strip()
                    size = max(1, int(size_str)) if size_str.isdigit() else 1
                    self._submit({"action": "add_combatant", "combatant": {
                        "name": name, "initiative": init, "hp": hp, "max_hp": max_hp,
                        "conditions": conditions, "icon": icon,
                        "is_pc": values.get('-IS_PC-', False),
                        "size": size,
                    }})
                    self._selected_index = None
                    self._submit({"action": "clear_selection"})
                    self._clear_form()
                except ValueError:
                    sg.popup('Initiative must be a whole number.')

        elif event == 'Apply Stats' and self._selected_index is not None:
            c = self.server.combatants[self._selected_index]
            old_name = c.name
            try:
                size_str = values.get('-SIZE-', '1').strip()
                fields = {
                    "name": values['-NAME-'],
                    "initiative": int(values['-INITIATIVE-']),
                    "hp": int(values['-HP-'].strip()) if values['-HP-'].strip() else None,
                    "max_hp": int(values['-MAX_HP-'].strip()) if values['-MAX_HP-'].strip() else None,
                    "is_pc": values.get('-IS_PC-', False),
                    "size": max(1, int(size_str)) if size_str.isdigit() else 1,
                }
            except ValueError:
                sg.popup('Initiative must be a whole number.')
                return
            self._submit({"action": "update_combatant", "name": old_name, "fields": fields})
            # server.combatants is already re-sorted; find new index by name
            new_name = fields["name"]
            for i, x in enumerate(self.server.combatants):
                if x.name == new_name:
                    self._selected_index = i
                    break
            self.refresh_table(self._selected_index)

        elif event == 'Delete Selected' and self._selected_index is not None:
            if 0 <= self._selected_index < len(self.server.combatants):
                name = self.server.combatants[self._selected_index].name
                self._submit({"action": "delete_combatant", "name": name})
            self._selected_index = None
            self._submit({"action": "clear_selection"})

        elif event in ('▲ Move Up', '▼ Move Down') and self._selected_index is not None:
            i = self._selected_index
            combatants = self.server.combatants
            if event == '▲ Move Up':
                j = i - 1
            else:
                j = i + 1
            if (0 <= j < len(combatants)
                    and combatants[i].initiative == combatants[j].initiative):
                name = combatants[i].name
                action_name = "move_up" if event == '▲ Move Up' else "move_down"
                self._submit({"action": action_name, "name": name})
                self._selected_index = j

        elif event == 'Wound' and self._selected_index is not None:
            try:
                name = self.server.combatants[self._selected_index].name
                self._submit({"action": "apply_damage", "name": name,
                                    "amount": int(values['-HP_CHANGE-'])})
                self.refresh_table(self._selected_index)
            except ValueError:
                sg.popup("Invalid damage value")
            self.window['-HP_CHANGE-'].update('0')

        elif event == 'Heal' and self._selected_index is not None:
            try:
                name = self.server.combatants[self._selected_index].name
                self._submit({"action": "apply_heal", "name": name,
                                    "amount": int(values['-HP_CHANGE-'])})
                self.refresh_table(self._selected_index)
            except ValueError:
                sg.popup("Invalid heal value")
            self.window['-HP_CHANGE-'].update('0')

        elif event == '⏭ Next Char':
            self._submit({"action": "advance_turn"})
            self._selected_index = None
            self._clear_form()
            self.window['-TURN-'].update(str(self.server.turn))
            self.refresh_table()

        elif event == '⏮ Prev Char':
            self._submit({"action": "retreat_turn"})
            self._selected_index = None
            self._clear_form()
            self.window['-TURN-'].update(str(self.server.turn))
            self.refresh_table()

        elif event == 'Toggle Selection':
            sel = values.get('-PLAYERS-')
            if sel:
                player_names = list(self._connected_players.keys())
                idx = sel[0]
                if 0 <= idx < len(player_names):
                    name = player_names[idx]
                    current = self._connected_players[name]["select"]
                    self._submit({"action": "set_player_lock", "name": name,
                                  "lock_type": "select", "locked": not current})

        elif event == 'Toggle Movement':
            sel = values.get('-PLAYERS-')
            if sel:
                player_names = list(self._connected_players.keys())
                idx = sel[0]
                if 0 <= idx < len(player_names):
                    name = player_names[idx]
                    current = self._connected_players[name]["move"]
                    self._submit({"action": "set_player_lock", "name": name,
                                  "lock_type": "move", "locked": not current})

        elif event == 'Load Map':
            path = sg.popup_get_file(
                'Select dungeon map file',
                file_types=(('Map Files', '*.txt'),),
                keep_on_top=True,
            )
            if path:
                self._submit({"action": "load_map", "path": path})

        elif event == 'Toggle Map':
            self._submit({"action": "set_map_visible", "visible": not self._map_visible})

        elif event == '-SIGHT_RADIUS-':
            self._submit({"action": "set_visibility_radius",
                          "radius": int(values['-SIGHT_RADIUS-'])})

        elif event == 'Toggle Chat':
            if self._chat and self._chat.is_open():
                self._chat.close()
                self.window['Toggle Chat'].update(text='Open Chat')
            else:
                self._chat.open(self._pc_names())
                self.window['Toggle Chat'].update(text='Close Chat')
                self._chat.mark_current_tab_read()
                if not self._chat._unread:
                    self.window['-CHAT_NOTIFY-'].update('')

        elif event == '💾 Export':
            default_name = f'combat_tracker_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            path = sg.popup_get_file(
                "Save tracker as",
                save_as=True,
                initial_folder=os.path.join(dir_path, 'Savegames'),
                default_path=default_name,
                file_types=(("JSON Files", "*.json"),),
            )
            if path:
                if not path.endswith('.json'):
                    path += '.json'
                self._submit({"action": "save", "path": path})
                sg.popup(f"Saved to {path}")

        elif event == '📂 Load':
            file_path = sg.popup_get_file("Select tracker file", initial_folder=os.path.join(dir_path, 'Savegames'),
                                          file_types=(("JSON Files", "*.json"),))
            if file_path:
                self._selected_index = None
                self._clear_form()
                self._submit({"action": "load", "path": file_path})

    def run_gui(self, dir_path):
        """Build and run the tracker GUI event loop.  Blocks until the window is closed.

        Args:
            dir_path: Base directory used to resolve save/load file paths.
        """
        layout = self.build_gui_layout()
        self.window = sg.Window('D&D Initiative Tracker', layout, resizable=True, finalize=True)

        # Intercept window close at Tk level — read_all_windows destroys the window
        # before we see WIN_CLOSED, so we replace WM_DELETE_WINDOW entirely.
        # We must NOT call popup from here (nested mainloop → unstable).
        # Just post an event; the read_all_windows loop shows the popup safely.
        self.window.TKroot.protocol(
            "WM_DELETE_WINDOW",
            lambda: self.window.write_event_value('-CLOSE_REQUESTED-', None),
        )

        # Override the ttk Treeview style — the Windows 'vista' theme applies bold
        # to row text regardless of the font argument passed to the Table element.
        import tkinter.ttk as ttk
        ttk.Style().configure('Treeview', font=(_UI_FONT, 16, 'normal'))

        tree = self.window['-TABLE-'].Widget
        tree.bind('<Double-Button-1>', self._start_notes_edit)
        if _PIL_OK:
            tree.configure(show='tree headings')
            tree.column('#0', width=150, stretch=False, anchor='w')
            tree.heading('#0', text='')

        self.refresh_table()
        self._squelch_table_event = 0  # initial populate doesn't fire a TABLE event; reset to avoid eating first click
        # Restore map UI state from server (save may have been loaded before window opened)
        self._sync_map_ui(self.server.map_path, self.server.map_visible)
        self.window['-SIGHT_RADIUS-'].update(value=self.server.visibility_radius)

        # Open chat window at startup
        self._chat = ChatWindow(submit_fn=self._submit)
        self._chat.open(self._pc_names())

        while True:
            win, event, values = sg.read_all_windows(timeout=100)

            if win is None:
                continue  # timeout with no event

            if win == self.window:
                if event == '-CLOSE_REQUESTED-':
                    if sg.popup_yes_no('Are you sure you want to quit DungeonPy?',
                                       title='Quit', keep_on_top=True) == 'Yes':
                        break
                    continue
                if event == sg.WIN_CLOSED:
                    break  # fallback if window destroyed externally
                if event == 'SERVER_EVENT':
                    self._apply_server_event(values[event])
                    continue
                self.handle_event(event, values, dir_path)

            elif win == (self._chat.window if self._chat else None):
                keep = self._chat.handle_event(event, values)
                if not keep:
                    self.window['Toggle Chat'].update(text='Open Chat')
                if not self._chat._unread:
                    self.window['-CHAT_NOTIFY-'].update('')

        if self._chat:
            self._chat.close()
        self.window.close()
        os._exit(0)
