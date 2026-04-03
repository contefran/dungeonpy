from datetime import datetime
import io
import os
import sys
import tkinter as tk
import PySimpleGUI as sg
from Core.combatant import Combatant
from Core.log_utils import log

try:
    from PIL import Image, ImageDraw, ImageFont as PILFont, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

_NOTO_COLOR_EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
CONDITION_ICON_SIZE = 36 # pixels

_COND_ABBREV = {
    'Blind': 'Bln', 'Charmed': 'Chr', 'Deaf': 'Def', 'Frightened': 'Frt',
    'Grappled': 'Grp', 'Incapacitated': 'Inc', 'Invisible': 'Inv', 'Paralyzed': 'Par',
    'Petrified': 'Pet', 'Poisoned': 'Poi', 'Prone': 'Prn', 'Restrained': 'Rst',
    'See-invisible': 'SeI', 'Stunned': 'Stn', 'Unconscious': 'Unc', 'Dead': 'Ded',
}


def _render_emoji_png(char: str, size: int = 22) -> bytes | None:
    """Render a single emoji as a colour PNG via NotoColorEmoji. Returns None on failure."""
    if not _PIL_OK or not os.path.exists(_NOTO_COLOR_EMOJI):
        return None
    try:
        font = PILFont.truetype(_NOTO_COLOR_EMOJI, 109)  # 109 = native bitmap size
        dummy = Image.new("RGBA", (1, 1))
        bbox = ImageDraw.Draw(dummy).textbbox((0, 0), char, font=font, embedded_color=True)
        w = max(1, bbox[2] - bbox[0])
        h = max(1, bbox[3] - bbox[1])
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((-bbox[0], -bbox[1]), char, font=font, embedded_color=True)
        img = img.resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


class Tracker:

    def __init__(self, server, submit=None, dir_path='', verbose=False, super_verbose=False):
        self.server = server
        self._submit = submit if submit is not None else server.submit
        self.dir_path = dir_path
        self.verbose = verbose
        self.super_verbose = super_verbose
        self._squelch_table_event = False
        self._selected_index = None
        self._pending_timers = {}   # condition → expiry turn, set during the current edit session
        self.window = None

        condition_dict = {
            'Blind': '🙈',
            'Charmed': '💘',
            'Deaf': '🙉',
            'Frightened': '😱',
            'Grappled': '🤼',
            'Incapacitated': '💤',
            'Invisible': '👻',
            'Paralyzed': '🧊',
            'Petrified': '🗿',
            'Poisoned': '🩸',
            'Prone': '🛌',
            'Restrained': '⛓',
            'See-invisible': '👁',
            'Stunned': '😵',
            'Unconscious': '🛑',
            'Dead': '💀',
        }
        self.condition_list = list(condition_dict.keys())

        def sanitize_emoji(s: str) -> str:  # remove U+FE0F (variation selector-16)
            return s.replace('\ufe0f', '')

        if sys.platform.startswith("linux"):
            self.condition_icons = {k: sanitize_emoji(v) for k, v in condition_dict.items()}
        else:
            self.condition_icons = dict(condition_dict)

        # Load condition images: PNG files take priority, emoji rendering is the fallback.
        self.condition_images = self._load_condition_images()
        self._table_photos = {}   # keeps ImageTk.PhotoImage refs alive (tkinter GC guard)

        if self.verbose:
            log("[Tracker] Tracker module loaded.")

    # ------------------------------------------------------------------
    # Condition image loading
    # ------------------------------------------------------------------

    def _load_condition_images(self) -> dict:
        """
        Return {condition_name: png_bytes} for each condition.
        Prefers Icons/Conditions/<name>.png; falls back to emoji rendering.
        """
        images = {}
        for cond in self.condition_list:
            png_path = os.path.join(self.dir_path, 'Icons', 'Conditions', f'{cond}.png')
            if os.path.isfile(png_path):
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
            else:
                images[cond] = _render_emoji_png(self.condition_icons[cond])
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
            # Refresh table with current selection; _selected_index was set by caller
            self.window['-TURN-'].update(str(self.server.turn))
            self.refresh_table(self._selected_index)
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

        elif action == "selection_changed":
            name = event["name"]
            for i, c in enumerate(self.server.combatants):
                if c.name == name:
                    # Only highlight the row if selection actually moved (avoids echo from our own click)
                    if i != self._selected_index:
                        self._selected_index = i
                        self._squelch_table_event = True
                        self.window['-TABLE-'].update(select_rows=[i + 1])
                    self.window['-NAME-'].update(c.name)
                    self.window['-INITIATIVE-'].update(c.initiative)
                    self.window['-HP-'].update('' if c.hp is None else c.hp)
                    self.window['-MAX_HP-'].update('' if c.max_hp is None else c.max_hp)
                    for cond in self.condition_list:
                        self.window[f'-COND_{cond}-'].update(cond in c.conditions)
                    self.window.refresh()
                    break

        elif action == "selection_cleared":
            if self._selected_index is not None:
                self._selected_index = None
                self._squelch_table_event = True
                self.window['-TABLE-'].update(select_rows=[])
            self._clear_form()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clear_form(self):
        self.window['-NAME-'].update('')
        self.window['-INITIATIVE-'].update('')
        self.window['-HP-'].update('')
        self.window['-MAX_HP-'].update('')
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

        if self.verbose:
            print(f'Platform: {sys.platform}')
        if sys.platform == "win32":
            emoji_font = ("Segoe UI Emoji", 12)
        elif sys.platform == "darwin":
            emoji_font = ("Apple Color Emoji", 12)
        else:
            emoji_font = ("Noto Emoji", 12)
        table_font = ("Helvetica", 16)

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
                else:
                    row_elements.append(sg.Checkbox(
                        f"{self.condition_icons[cond]} {cond}", key=f'-COND_{cond}-', font=emoji_font,
                        size=(COND_COL_WIDTH, 1), enable_events=True
                    ))
            condition_rows.append(row_elements)

        layout = [
            [sg.Text('Initiative Tracker', font=table_font)],
            [sg.Table(values=[], headings=['Name', 'Initiative', 'HP', 'Notes'],
                      auto_size_columns=False, justification='left', col_widths=[10, 10, 10, 40],
                      key='-TABLE-', enable_events=True, row_height=36, expand_x=True, num_rows=10,
                      background_color='white', text_color='black', font=table_font)],
            [sg.Text('Turn:', font=table_font), sg.Input(str(self.server.turn), key='-TURN-', size=(5, 1)),
             sg.Button('⏮ Prev Char'), sg.Button('⏭ Next Char')],
            [sg.HorizontalSeparator()],
            [sg.Text('Name', size=(10, 1), font=table_font), sg.Input(key='-NAME-', size=(30, 1))],
            [sg.Text('Initiative', size=(10, 1), font=table_font), sg.Input(key='-INITIATIVE-', size=(5, 1))],
            [sg.Text('HP:', size=(10, 1), font=table_font), sg.Input(key='-HP-', size=(5, 1)),
             sg.Text('Max HP:', font=table_font), sg.Input(key='-MAX_HP-', size=(5, 1)),
             sg.Text('   Change:', font=table_font), sg.Input('0', key='-HP_CHANGE-', size=(5, 1)),
             sg.Button('Wound'), sg.Button('Heal')],
            [sg.Text('Conditions:', font=table_font)],
            *condition_rows,
            [
                sg.Button('Add New'), sg.Button('Update Selected'), sg.Button('Delete Selected'), sg.Button('💾 Export'), sg.Button('📂 Load')]
        ]
        return layout

    def refresh_table(self, selected_index=None):
        data = [['', '', '', '']]  # blank row for deselection
        row_conditions = [[]]  # parallel list of condition lists per row
        for i, c in enumerate(self.server.combatants):
            name = f"→ {c.name}" if i == self.server.active_index else c.name
            timer_parts = [f"{_COND_ABBREV.get(cond, cond[:3])}:{exp[0]}@{exp[1]}"
                           for cond, exp in sorted(c.condition_timers.items())]
            notes_display = c.notes + (" [" + ", ".join(timer_parts) + "]" if timer_parts else "")
            data.append([name, c.initiative, '' if c.hp is None else c.hp, notes_display])
            row_conditions.append(list(c.conditions))

        self._squelch_table_event = True
        if selected_index is not None and 0 <= selected_index < len(self.server.combatants):
            self.window['-TABLE-'].update(values=data, select_rows=[selected_index + 1])
        else:
            self.window['-TABLE-'].update(values=data, select_rows=[])
        self._squelch_table_event = False

        tree = self.window['-TABLE-'].Widget
        tree.tag_configure('dead', font=('Helvetica', 12, 'overstrike'))
        new_photos = {}
        for item_id, conditions in zip(tree.get_children(), row_conditions):
            tags = ('dead',) if 'Dead' in conditions else ()
            if _PIL_OK:
                photo = self._make_condition_strip(conditions)
                tree.item(item_id, text='', image=photo if photo else '', tags=tags)
                if photo:
                    new_photos[item_id] = photo
            else:
                tree.item(item_id, tags=tags)
        self._table_photos = new_photos  # replace; old refs released

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_event(self, event, values, dir_path):
        if event == sg.WIN_CLOSED:
            return

        if event == '-TABLE-' and self._squelch_table_event:
            self._squelch_table_event = False
            return

        if self.verbose:
            log(f"[Tracker] Event: {event}")

        if event == '-TABLE-':
            try:
                if values['-TABLE-']:
                    row_index = values['-TABLE-'][0]
                    if self.verbose:
                        log(f"[Tracker] Handling row selection: {row_index}")
                    if row_index == 0:
                        self._selected_index = None
                        self._submit({"action": "clear_selection"})
                        self.window['-TABLE-'].update(select_rows=[])
                        self._clear_form()
                    else:
                        self._selected_index = row_index - 1
                        c = self.server.combatants[self._selected_index]
                        if self.verbose:
                            log(f"[Tracker] Selected index = {self._selected_index}, Combatant: {c}")
                        self.window['-NAME-'].update(c.name)
                        self.window['-INITIATIVE-'].update(c.initiative)
                        self.window['-HP-'].update('' if c.hp is None else c.hp)
                        self.window['-MAX_HP-'].update('' if c.max_hp is None else c.max_hp)
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
                    [sg.Text('(leave Rounds blank for permanent)', font=('Helvetica', 10))],
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
            else:  # condition turned OFF
                self._pending_timers.pop(cond, None)

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
                        initial_folder=os.path.join(dir_path, 'Icons'),
                        file_types=(("Image Files", "*.png *.jpg *.jpeg"),),
                        no_window=False,
                    )
                    icon = os.path.basename(icon_path) if icon_path else None
                    self._submit({"action": "add_combatant", "combatant": {
                        "name": name, "initiative": init, "hp": hp, "max_hp": max_hp,
                        "conditions": conditions, "icon": icon,
                    }})
                    self._selected_index = None
                    self._submit({"action": "clear_selection"})
                    self._clear_form()
                except ValueError:
                    sg.popup('Initiative must be a whole number.')

        elif event == 'Update Selected' and self._selected_index is not None:
            c = self.server.combatants[self._selected_index]
            old_name = c.name
            try:
                new_conditions = [cond for cond in self.condition_list if values.get(f'-COND_{cond}-')]
                # Keep existing timers only for conditions that are still active
                new_timers = {cond: t for cond, t in c.condition_timers.items()
                              if cond in new_conditions}
                # Pending timers (set this session) override existing ones
                new_timers.update(self._pending_timers)
                self._pending_timers = {}
                fields = {
                    "name": values['-NAME-'],
                    "initiative": int(values['-INITIATIVE-']),
                    "hp": int(values['-HP-'].strip()) if values['-HP-'].strip() else None,
                    "max_hp": int(values['-MAX_HP-'].strip()) if values['-MAX_HP-'].strip() else None,
                    "conditions": new_conditions,
                    "condition_timers": new_timers,
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

        elif event == '💾 Export':
            path = os.path.join(dir_path, f'Data/combat_tracker_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
            self._submit({"action": "save", "path": path})
            sg.popup(f"Saved to {path}")

        elif event == '📂 Load':
            file_path = sg.popup_get_file("Select tracker file", initial_folder=dir_path + "Data",
                                          file_types=(("JSON Files", "*.json"),))
            if file_path:
                self._selected_index = None
                self._clear_form()
                self._submit({"action": "load", "path": file_path})

    def run_gui(self, dir_path):
        layout = self.build_gui_layout()
        self.window = sg.Window('D&D Initiative Tracker', layout, resizable=True, finalize=True,
                                enable_close_attempted_event=True)

        tree = self.window['-TABLE-'].Widget
        tree.bind('<Double-Button-1>', self._start_notes_edit)
        if _PIL_OK:
            tree.configure(show='tree headings')
            tree.column('#0', width=150, stretch=False, anchor='w')
            tree.heading('#0', text='')

        self.refresh_table()
        while True:
            event, values = self.window.read()
            if event == sg.WINDOW_CLOSE_ATTEMPTED_EVENT:
                if sg.popup_yes_no('Are you sure you want to quit DungeonPy?',
                                   title='Quit', keep_on_top=True) == 'Yes':
                    break
                else:
                    continue
            if event == 'SERVER_EVENT':
                self._apply_server_event(values[event])
                continue
            self.handle_event(event, values, dir_path)

        self.window.close()
        os._exit(0)
