from datetime import datetime
import io
import os
import sys
import json
import PySimpleGUI as sg
from Core.combatant import Combatant
from Core.socket_bridge import SocketBridge
from Core.log_utils import log
import Core.protocol as proto

try:
    from PIL import Image, ImageDraw, ImageFont as PILFont, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

_NOTO_COLOR_EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"


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

    def __init__(self, verbose=False, super_verbose=False):
        self.combatants = []
        self.active_index = 0
        self.turn = 1
        self.verbose = verbose
        self.super_verbose = super_verbose
        self._squelch_table_event = False  # to avoid feedback loops when updating table from the map
        self.on_load = None              # optional callback set by Game to resync the map after a load
        self.on_combatant_added = None   # optional callback set by Game to add new combatant to the map queue

        condition_dict = {
            'Blind': '🙈',
            'Charm': '💘',
            'Deaf': '🙉',
            'Fright': '😱',
            'Grapple': '🤼',
            'Incap': '💤',
            'Invis': '👻',
            'Paral': '🧊',
            'Petr': '🗿',
            'Poison': '🩸',
            'Prone': '🛌',
            'Restrain': '⛓',
            'See-inv': '👁',
            'Stun': '😵',
            'Uncon': '🛑',
            'Down': '💀',
        }
        self.condition_list = list(condition_dict.keys())

        def sanitize_emoji(s: str) -> str:  # remove U+FE0F (variation selector-16)
            return s.replace('\ufe0f', '')

        if sys.platform.startswith("linux"):
            self.condition_icons = {k: sanitize_emoji(v) for k, v in condition_dict.items()}
        else:
            self.condition_icons = dict(condition_dict)

        # Pre-render each condition emoji as a colour PNG (None if PIL unavailable)
        self.condition_images = {
            cond: _render_emoji_png(icon)
            for cond, icon in self.condition_icons.items()
        }
        self._table_photos = {}   # keeps ImageTk.PhotoImage refs alive (tkinter GC guard)

        self.bridge = SocketBridge(65432, on_message=self._handle_incoming_message, verbose=self.verbose)
        self.window = None

        if self.verbose:
            log("[Tracker] Tracker module loaded.")


    def _handle_incoming_message(self, message):
        # Never touch the GUI here; this runs on the socket thread.
        # Just post an event back to the GUI thread.
        if self.verbose:
            log(f"[Tracker] (socket thread) Incoming message: {message}")
        if not self.window:
            return
        self.window.write_event_value('SOCKET_MSG', message)


    def _process_socket_message_on_gui_thread(self, message):
        if self.verbose:
            log(f"[Tracker] (GUI thread) Processing socket message: {message}")
        msg = proto.parse(message)
        if msg is None:
            return
        if msg["type"] == proto.TYPE_CLEAR:
            if self.verbose:
                log("[Tracker] (GUI thread) Clearing selection")
            self._squelch_table_event = True
            self.window['-TABLE-'].update(select_rows=[])
            self.window['-NAME-'].update('')
            self.window['-INITIATIVE-'].update('')
            self.window['-HP-'].update('')
            for cond in self.condition_list:
                self.window[f'-COND_{cond}-'].update(False)
        elif msg["type"] == proto.TYPE_SELECTED:
            name = msg["name"]
            for i, c in enumerate(self.combatants):
                if self.super_verbose:
                    log(f"[Tracker] (GUI thread) Going through combatants: {i}, {c.name}")
                if c.name == name:
                    if self.verbose:
                        log(f"[Tracker] (GUI thread) Selecting row {i+1}, character {name}")
                    self._squelch_table_event = True
                    self.window['-TABLE-'].update(select_rows=[i + 1])
                    self.window['-NAME-'].update(c.name)
                    self.window['-INITIATIVE-'].update(c.initiative)
                    self.window['-HP-'].update('' if c.hp is None else c.hp)
                    for cond in self.condition_list:
                        self.window[f'-COND_{cond}-'].update(cond in c.conditions)
                    break
        elif msg["type"] == proto.TYPE_ACTIVE:
            name = msg["name"]
            for i, c in enumerate(self.combatants):
                if c.name == name:
                    self.active_index = i
                    self.window['-TURN-'].update(str(self.turn))
                    self.refresh_table()
                    break


    def send_to_map(self, message):
        if self.verbose:
            log(f"[Tracker] Sending to map: {message}")
        self.bridge.send(65433, message)


    def load_from_file(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        new_combatants = [Combatant.from_dict(c) for c in data.get("initiative", [])]
        self.combatants.clear()
        self.combatants.extend(new_combatants)
        self.active_index = data.get("active_index", 0)
        self.turn = data.get("turn", 1)
        if self.on_load:
            self.on_load()
        if self.verbose:
            log(f"[Tracker] Loaded {len(self.combatants)} combatants from {filepath}")


    def save_to_file(self, filepath):
        data = {
            "initiative": [c.to_dict() for c in self.combatants],
            "active_index": self.active_index,
            "turn": self.turn
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        if self.verbose:
            log(f"[Tracker] Saved tracker state to {filepath}")


    def add(self, combatant: Combatant):
        self.combatants.append(combatant)
        self.sort_by_initiative()
        if self.verbose:
            log(f"[Tracker] Added combatant: {combatant.name} (init {combatant.initiative})")


    def sort_by_initiative(self):
        self.combatants.sort(key=lambda c: c.initiative, reverse=True)


    def next(self):
        if not self.combatants:
            return None
        self.active_index = (self.active_index + 1) % len(self.combatants)
        if self.active_index == 0:
            self.turn += 1
        if self.verbose:
            log(f"[Tracker] Turn advanced: {self.turn}, Active: {self.get_active().name}")
        return self.get_active()


    def previous(self):
        if not self.combatants:
            return None
        if self.active_index == 0:
            self.active_index = len(self.combatants) - 1
            self.turn = max(1, self.turn - 1)
        else:
            self.active_index -= 1
        if self.verbose:
            log(f"[Tracker] Turn retreated: {self.turn}, Active: {self.get_active().name}")
        return self.get_active()


    def get_active(self):
        if 0 <= self.active_index < len(self.combatants):
            return self.combatants[self.active_index]
        return None


    def apply_damage(self, combatant, amount):
        current_hp = combatant.hp if combatant.hp is not None else 0
        combatant.hp = max(0, current_hp - amount)
        if combatant.hp == 0 and "Down" not in combatant.conditions:
            combatant.conditions.append("Down")

    def apply_heal(self, combatant, amount):
        current_hp = combatant.hp if combatant.hp is not None else 0
        combatant.hp = current_hp + amount
        if combatant.hp > 0 and "Down" in combatant.conditions:
            combatant.conditions.remove("Down")

    def select_by_name(self, name):
        for i, c in enumerate(self.combatants):
            if c.name == name:
                self.active_index = i
                return c
        return None


    def _make_condition_strip(self, conditions: list):
        """Return an ImageTk.PhotoImage strip of condition icons, or None."""
        if not _PIL_OK or not conditions:
            return None
        size, gap = 22, 2
        imgs = []
        for cond in conditions:
            raw = self.condition_images.get(cond)
            if raw:
                imgs.append(Image.open(io.BytesIO(raw)).convert("RGBA"))
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
        table_font = ("Helvetica", 12)

        condition_rows = []
        for row_conds in chunk(self.condition_list, 5):
            row_elements = []
            for cond in row_conds:
                img_data = self.condition_images.get(cond)
                if img_data:
                    row_elements.append(sg.Image(data=img_data))
                    row_elements.append(sg.Checkbox(cond, key=f'-COND_{cond}-', font=table_font))
                else:
                    row_elements.append(sg.Checkbox(
                        f"{self.condition_icons[cond]} {cond}", key=f'-COND_{cond}-', font=emoji_font
                    ))
            condition_rows.append(row_elements)

        layout = [
            [sg.Text('Initiative Tracker', font=table_font)],
            [sg.Table(values=[], headings=['Name', 'Initiative', 'HP'],
                      auto_size_columns=False, justification='left', col_widths=[20, 10, 10],
                      key='-TABLE-', enable_events=True, row_height=28, expand_x=True, num_rows=10,
                      background_color='white', text_color='black', font=table_font)],
            [sg.Text('Turn:', font=table_font), sg.Input(str(self.turn), key='-TURN-', size=(5, 1)),
             sg.Button('⏮ Prev Char'), sg.Button('⏭ Next Char')],
            [sg.HorizontalSeparator()],
            [sg.Text('Name', size=(10, 1), font=table_font), sg.Input(key='-NAME-', size=(30, 1))],
            [sg.Text('Initiative', size=(10, 1), font=table_font), sg.Input(key='-INITIATIVE-', size=(5, 1))],
            [sg.Text('HP:', size=(10, 1), font=table_font), sg.Input(key='-HP-', size=(5, 1)),
             sg.Text('   Change:', font=table_font), sg.Input('0', key='-HP_CHANGE-', size=(5, 1)),
             sg.Button('Wound'), sg.Button('Heal')],
            [sg.Text('Conditions:', font=table_font)],
            *condition_rows,
            [
                sg.Button('Add New'), sg.Button('Update Selected'),
                sg.Button('Delete Selected'), sg.Button('↑ Move Up'), sg.Button('↓ Move Down')
            ],
            [sg.Button('💾 Export'), sg.Button('📂 Load')]
        ]
        return layout


    def refresh_table(self, selected_index=None):
        data = [['', '', '']]  # blank row for deselection
        row_conditions = [[]]  # parallel list of condition lists per row
        for i, c in enumerate(self.combatants):
            name = f"→ {c.name}" if i == self.active_index else c.name
            data.append([name, c.initiative, '' if c.hp is None else c.hp])
            row_conditions.append(list(c.conditions))

        self._squelch_table_event = True
        if selected_index is not None and 0 <= selected_index < len(self.combatants):
            self.window['-TABLE-'].update(values=data, select_rows=[selected_index + 1])
        else:
            self.window['-TABLE-'].update(values=data, select_rows=[])
        self._squelch_table_event = False

        if _PIL_OK:
            tree = self.window['-TABLE-'].Widget
            new_photos = {}
            for item_id, conditions in zip(tree.get_children(), row_conditions):
                photo = self._make_condition_strip(conditions)
                tree.item(item_id, text='', image=photo if photo else '')
                if photo:
                    new_photos[item_id] = photo
            self._table_photos = new_photos  # replace; old refs released


    def handle_event(self, event, values, selected_index_ref, dir_path):
        selected_index = selected_index_ref[0]
        if self.verbose:
            log(f"[Tracker] Event: {event}")

        if event == sg.WIN_CLOSED:
            return

        if event == '-TABLE-':
            if self._squelch_table_event:
                self._squelch_table_event = False
                return
            try:
                if values['-TABLE-']:
                    row_index = values['-TABLE-'][0]
                    if self.verbose:
                        log(f"[Tracker] Handling row selection: {row_index}")
                    if row_index == 0:
                        selected_index = None
                        selected_index_ref[0] = None
                        self.send_to_map(proto.CLEAR_SELECTION)
                        self.window['-TABLE-'].update(select_rows=[])
                        self.window['-NAME-'].update('')
                        self.window['-INITIATIVE-'].update('')
                        self.window['-HP-'].update('')
                        for cond in self.condition_list:
                            self.window[f'-COND_{cond}-'].update(False)
                        self.window.refresh()
                    else:
                        selected_index = row_index - 1
                        selected_index_ref[0] = selected_index
                        c = self.combatants[selected_index]
                        if self.verbose:
                            log(f"[Tracker] Selected index = {selected_index}, Combatant selected: {c}")
                        self.window['-NAME-'].update(c.name)
                        self.window['-INITIATIVE-'].update(c.initiative)
                        self.window['-HP-'].update('' if c.hp is None else c.hp)
                        for cond in self.condition_list:
                            self.window[f'-COND_{cond}-'].update(cond in c.conditions)
                        self.send_to_map(proto.make_selected(c.name))
                        self.window.refresh()

            except Exception as e:
                print(f"Selection error: {e}")
                selected_index = None
                selected_index_ref[0] = None
                self.send_to_map(proto.CLEAR_SELECTION)

        elif event == 'Add New':
            try:
                name = values['-NAME-'].strip()
                init_str = values['-INITIATIVE-'].strip()
                if not name or not init_str:
                    sg.popup('Please enter a name and initiative value.')
                    return
                init = int(init_str)
                hp_str = values['-HP-'].strip()
                hp = int(hp_str) if hp_str else None
                conditions = [cond for cond in self.condition_list if values.get(f'-COND_{cond}-')]
                icon_path = sg.popup_get_file(
                    f"Select icon for {name} (close to skip)",
                    initial_folder=os.path.join(dir_path, 'Icons'),
                    file_types=(("Image Files", "*.png *.jpg *.jpeg"),),
                    no_window=False,
                )
                icon = os.path.basename(icon_path) if icon_path else None
                new_c = Combatant(name, init, hp, conditions, icon=icon)
                self.add(new_c)
                if self.on_combatant_added:
                    self.on_combatant_added(new_c)
                # Clear form and deselect after adding
                selected_index = None
                selected_index_ref[0] = None
                self.window['-NAME-'].update('')
                self.window['-INITIATIVE-'].update('')
                self.window['-HP-'].update('')
                for cond in self.condition_list:
                    self.window[f'-COND_{cond}-'].update(False)
                self.send_to_map(proto.CLEAR_SELECTION)
                self.refresh_table()
            except ValueError:
                sg.popup('Initiative must be a whole number.')

        elif event == 'Update Selected' and selected_index is not None:
            c = self.combatants[selected_index]
            c.name = values['-NAME-']
            c.initiative = int(values['-INITIATIVE-'])
            hp_str = values['-HP-'].strip()
            c.hp = int(hp_str) if hp_str else None
            c.conditions = [cond for cond in self.condition_list if values.get(f'-COND_{cond}-')]
            self.sort_by_initiative()
            for i, x in enumerate(self.combatants):
                if x is c:
                    selected_index = i
                    break
            selected_index_ref[0] = selected_index
            self.refresh_table(selected_index)

        elif event == 'Delete Selected' and selected_index is not None:
            if 0 <= selected_index < len(self.combatants):
                self.combatants.pop(selected_index)
                if not self.combatants:
                    self.active_index = 0
                elif selected_index == self.active_index:
                    self.active_index = min(self.active_index, len(self.combatants) - 1)
                elif selected_index < self.active_index:
                    self.active_index -= 1
            selected_index = None
            selected_index_ref[0] = None
            self.send_to_map(proto.CLEAR_SELECTION)
            self.refresh_table()

        elif event == '↑ Move Up' and selected_index is not None and selected_index > 0:
            self.combatants[selected_index], self.combatants[selected_index - 1] = \
                self.combatants[selected_index - 1], self.combatants[selected_index]
            if selected_index == self.active_index:
                self.active_index -= 1
            elif selected_index - 1 == self.active_index:
                self.active_index += 1
            selected_index -= 1
            selected_index_ref[0] = selected_index
            self.refresh_table(selected_index)

        elif event == '↓ Move Down' and selected_index is not None and selected_index < len(self.combatants) - 1:
            self.combatants[selected_index], self.combatants[selected_index + 1] = \
                self.combatants[selected_index + 1], self.combatants[selected_index]
            if selected_index == self.active_index:
                self.active_index += 1
            elif selected_index + 1 == self.active_index:
                self.active_index -= 1
            selected_index += 1
            selected_index_ref[0] = selected_index
            self.refresh_table(selected_index)

        elif event == 'Wound' and selected_index is not None:
            try:
                self.apply_damage(self.combatants[selected_index], int(values['-HP_CHANGE-']))
                self.refresh_table(selected_index)
            except ValueError:
                sg.popup("Invalid damage value")

        elif event == 'Heal' and selected_index is not None:
            try:
                self.apply_heal(self.combatants[selected_index], int(values['-HP_CHANGE-']))
                self.refresh_table(selected_index)
            except ValueError:
                sg.popup("Invalid heal value")

        elif event == '⏭ Next Char':
            self.next()
            active = self.get_active()
            selected_index_ref[0] = None
            self.send_to_map(proto.CLEAR_SELECTION)
            self.window['-NAME-'].update('')
            self.window['-INITIATIVE-'].update('')
            self.window['-HP-'].update('')
            for cond in self.condition_list:
                self.window[f'-COND_{cond}-'].update(False)
            if active:
                self.send_to_map(proto.make_active(active.name))
            self.window['-TURN-'].update(str(self.turn))
            self.refresh_table()

        elif event == '⏮ Prev Char':
            self.previous()
            active = self.get_active()
            selected_index_ref[0] = None
            self.send_to_map(proto.CLEAR_SELECTION)
            self.window['-NAME-'].update('')
            self.window['-INITIATIVE-'].update('')
            self.window['-HP-'].update('')
            for cond in self.condition_list:
                self.window[f'-COND_{cond}-'].update(False)
            if active:
                self.send_to_map(proto.make_active(active.name))
            self.window['-TURN-'].update(str(self.turn))
            self.refresh_table()

        elif event == '💾 Export':
            path = os.path.join(dir_path, f'Data/combat_tracker_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
            self.save_to_file(path)
            sg.popup(f"Saved to {path}")

        elif event == '📂 Load':
            file_path = sg.popup_get_file("Select tracker file", initial_folder=dir_path + "Data", file_types=(("JSON Files", "*.json"),))
            if file_path:
                self.load_from_file(file_path)
                self.window['-TURN-'].update(str(self.turn))
                selected_index = None
                selected_index_ref[0] = None
                self.send_to_map(proto.CLEAR_SELECTION)
                self.refresh_table()


    def run_gui(self, dir_path):
        layout = self.build_gui_layout()
        self.window = sg.Window('D&D Initiative Tracker', layout, resizable=True, finalize=True)

        if _PIL_OK:
            tree = self.window['-TABLE-'].Widget
            tree.configure(show='tree headings')
            tree.column('#0', width=150, stretch=False, anchor='w')
            tree.heading('#0', text='')

        selected_index = [None]
        self.refresh_table()
        while True:
            event, values = self.window.read()
            if event == sg.WIN_CLOSED:
                break
            if event == 'SOCKET_MSG':
                self._process_socket_message_on_gui_thread(values[event])
                continue
            self.handle_event(event, values, selected_index, dir_path)

        self.window.close()
