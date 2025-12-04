from datetime import datetime
import json
import PySimpleGUI as sg
from Core.combatant import Combatant
from Core.socket_bridge import SocketBridge


print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
print("[Tracker] Tracker module loaded.")

class Tracker:
    
    def __init__(self, verbose=False, super_verbose=False):
        self.combatants = []
        self.active_index = 0
        self.turn = 1
        self.verbose = verbose
        self.super_verbose = super_verbose

        self.condition_icons = {
            'Blinded': '🙈', 'Charmed': '💘', 'Deafened': '🙉', 'Frightened': '😱',
            'Grappled': '🤼', 'Incapacitated': '💤', 'Invisible': '👻', 'Paralyzed': '🧊',
            'Petrified': '🪨', 'Poisoned': '🩸', 'Prone': '🛌', 'Restrained': '⛓️',
            'See invisible': '👁️', 'Stunned': '😵', 'Unconscious': '🛑', 'Down': '💀'
        }
        self.conditions_list = list(self.condition_icons.keys())

        self.bridge = SocketBridge(65432, on_message=self._handle_incoming_message, verbose=self.verbose)
        
        self.window = None


    def _handle_incoming_message(self, message):
        if not self.window:
            return

        if self.verbose:
            print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
            print(f"[Tracker] Received message: {message}")

        if message == "CLEAR_SELECTION":
            self.window['-TABLE-'].update(select_rows=[])
            self.window['-NAME-'].update('')
            self.window['-INITIATIVE-'].update('')
            self.window['-HP-'].update('')
            for cond in self.conditions_list:
                self.window[f'-COND_{cond}-'].update(False)
        elif message.endswith(" selected"):
            name = message.replace(" selected", "")
            for i, c in enumerate(self.combatants):
                if self.super_verbose:
                    print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
                    print(f"[Tracker] Going through combatants: {i}, {c.name}")
                if c.name == name:
                    if self.super_verbose:
                        print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
                        print(f"Selecting row {i+1}") # because of the blank row at the top
                    self.window['-TABLE-'].update(select_rows=[i+1])
                    break
        elif message.endswith(" active"):
            name = message.replace(" active", "")
            for i, c in enumerate(self.combatants):
                if c.name == name:
                    self.active_index = i
                    self.window['-TURN-'].update(str(self.turn))
                    self.refresh_table()
                    break


    def send_to_map(self, message):
        if self.verbose:
            print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
            print(f"[Tracker] Sending to map: {message}")
        self.bridge.send(65433, message)


    def load_from_file(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.combatants = [Combatant.from_dict(c) for c in data.get("initiative", [])]
        self.active_index = data.get("active_index", 0)
        self.turn = data.get("turn", 1)
        if self.verbose:
            print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
            print(f"[Tracker] Loaded {len(self.combatants)} combatants from {filepath}")


    def save_to_file(self, filepath):
        data = {
            "initiative": [c.to_dict() for c in self.combatants],
            "active_index": self.active_index,
            "turn": self.turn
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        if self.verbose:
            print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
            print(f"[Tracker] Saved tracker state to {filepath}")


    def add(self, combatant: Combatant):
        self.combatants.append(combatant)
        self.sort_by_initiative()
        if self.verbose:
            print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
            print(f"[Tracker] Added combatant: {combatant.name} (init {combatant.initiative})")


    def sort_by_initiative(self):
        self.combatants.sort(key=lambda c: c.initiative, reverse=True)


    def next(self):
        if not self.combatants:
            return None
        self.active_index = (self.active_index + 1) % len(self.combatants)
        if self.active_index == 0:
            self.turn += 1
        if self.verbose:
            print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
            print(f"[Tracker] Turn advanced: {self.turn}, Active: {self.get_active().name}")
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
            print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
            print(f"[Tracker] Turn advanced: {self.turn}, Active: {self.get_active().name}")
        return self.get_active()


    def get_active(self):
        if 0 <= self.active_index < len(self.combatants):
            return self.combatants[self.active_index]
        return None


    def select_by_name(self, name):
        for i, c in enumerate(self.combatants):
            if c.name == name:
                self.active_index = i
                return c
        return None


    def build_gui_layout(self):

        def chunk(lst, size):
            return [lst[i:i + size] for i in range(0, len(lst), size)]

        condition_rows = [
            [sg.Checkbox(f"{self.condition_icons[cond]} {cond}", key=f'-COND_{cond}-', font=('Segoe UI Emoji', 12))
            for cond in row]
            for row in chunk(self.conditions_list, 5)
        ]
        layout = [
            [sg.Text('Initiative Tracker', font=('Helvetica', 12))],
            [sg.Table(values=[], headings=['Name', 'Initiative', 'HP', 'Conditions'],
                    auto_size_columns=False, justification='left', col_widths=[20, 10, 10, 20],
                    key='-TABLE-', enable_events=True, row_height=25, expand_x=True, num_rows=10,
                    background_color='white', text_color='black', font=('Segoe UI Emoji', 12))],
            [sg.Text('Turn:', font=('Segoe UI Emoji', 12)), sg.Input(str(self.turn), key='-TURN-', size=(5, 1)),
            sg.Button('⏮ Prev Char'), sg.Button('⏭ Next Char')],
            [sg.HorizontalSeparator()],
            [sg.Text('Name', size=(10, 1)), sg.Input(key='-NAME-', size=(30, 1))],
            [sg.Text('Initiative', size=(10, 1)), sg.Input(key='-INITIATIVE-', size=(5, 1))],
            [sg.Text('HP (optional):', size=(12, 1)), sg.Input(key='-HP-', size=(5, 1)),
            sg.Text('   Change:'), sg.Input('0', key='-HP_CHANGE-', size=(5, 1)),
            sg.Button('Wound'), sg.Button('Heal')],
            [sg.Text('Conditions:')],
            *condition_rows,
            [
                sg.Button('Add New'), sg.Button('Update Selected'),
                sg.Button('Delete Selected'), sg.Button('↑ Move Up'), sg.Button('↓ Move Down')
            ],
            [sg.Button('💾 Export'), sg.Button('📂 Load')]
        ]
        return layout


    def refresh_table(self, selected_index=None):
        #data = []
        data = [['', '', '', '']]  # blank row for deselection
        for i, c in enumerate(self.combatants):
            icons = ''.join(self.condition_icons.get(cond, '') for cond in c.conditions)
            name = f"➡️ {c.name}" if i == self.active_index else c.name
            data.append([name, c.initiative, c.hp, icons])
        self.window['-TABLE-'].update(values=data)

        # Keep selection visible if we know it
        if selected_index is not None and 0 <= selected_index < len(self.combatants):
            self.window['-TABLE-'].update(select_rows=[selected_index + 1])  # +1 because of blank row


    def handle_event(self, event, values, selected_index_ref, dir_path):
        selected_index = selected_index_ref[0]
        if self.verbose:
            print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
            print(f"[Tracker] Event: {event}, index: {selected_index}")

        if event == sg.WIN_CLOSED:
            return

        if event == '-TABLE-':
            try:
                if values['-TABLE-']:
                    row_index = values['-TABLE-'][0] # table row index (0 = blank)
                    if self.verbose:
                        print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
                        print(f"[Tracker] Handling row selection: {row_index}")
                    if row_index == 0: # blank row selected
                        selected_index = None
                        selected_index_ref[0] = None
                        self.send_to_map("CLEAR_SELECTION")
                        self.window['-TABLE-'].update(select_rows=[])
                        self.window['-NAME-'].update('')
                        self.window['-INITIATIVE-'].update('')
                        self.window['-HP-'].update('')
                        for cond in self.conditions_list:
                            self.window[f'-COND_{cond}-'].update(False)
                        self.window.refresh()
                    else:
                        selected_index = row_index - 1
                        selected_index_ref[0] = selected_index
                        c = self.combatants[selected_index] # The combatant is clearly linked to the table row now
                        if self.verbose:
                            print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
                            print(f"[Tracker] Selected index = {selected_index}, Combatant selected: {c}")
                        self.window['-NAME-'].update(c.name)
                        self.window['-INITIATIVE-'].update(c.initiative)
                        self.window['-HP-'].update(c.hp)
                        for cond in self.conditions_list:
                            self.window[f'-COND_{cond}-'].update(cond in c.conditions)
                        self.send_to_map(f"{c.name} selected")
                        self.window.refresh()

            except Exception as e:
                print(f"Selection error: {e}")
                selected_index = None
                selected_index_ref[0] = None
                self.send_to_map("CLEAR_SELECTION")

        elif event == 'Add New':
            try:
                name = values['-NAME-']
                init = int(values['-INITIATIVE-'])
                hp = values['-HP-']
                conditions = [cond for cond in self.conditions_list if values.get(f'-COND_{cond}-')]
                new_c = Combatant(name, init, hp, conditions)
                self.add(new_c)
                # After sorting, find index of new combatant
                for i, c in enumerate(self.combatants):
                    if c is new_c:
                        selected_index = i
                        break
                selected_index_ref[0] = selected_index # Adjust accordingly
                self.refresh_table(selected_index)
            except ValueError:
                sg.popup('Invalid initiative value.')

        elif event == 'Update Selected' and selected_index is not None:
            c = self.combatants[selected_index]
            c.name = values['-NAME-']
            c.initiative = int(values['-INITIATIVE-'])
            c.hp = values['-HP-']
            c.conditions = [cond for cond in self.conditions_list if values.get(f'-COND_{cond}-')]
            self.sort_by_initiative() # just in case initiative changed
            # Check the new index of the updated combatant
            for i, x in enumerate(self.combatants):
                if x is c:
                    selected_index = i
                    break
            selected_index_ref[0] = selected_index
            self.refresh_table(selected_index)

        elif event == 'Delete Selected' and selected_index is not None:
            if 0 <= selected_index < len(self.combatants):
                self.combatants.pop(selected_index)
            selected_index = None # reset selection
            selected_index_ref[0] = None
            self.send_to_map("CLEAR_SELECTION")
            self.refresh_table()

        elif event == '↑ Move Up' and selected_index is not None and selected_index > 0:
            self.combatants[selected_index], self.combatants[selected_index - 1] = \
                self.combatants[selected_index - 1], self.combatants[selected_index]
            selected_index -= 1
            selected_index_ref[0] = selected_index
            self.refresh_table(selected_index)

        elif event == '↓ Move Down' and selected_index is not None and selected_index < len(self.combatants) - 1:
            self.combatants[selected_index], self.combatants[selected_index + 1] = \
                self.combatants[selected_index + 1], self.combatants[selected_index]
            selected_index += 1
            selected_index_ref[0] = selected_index
            self.refresh_table(selected_index)

        elif event == 'Wound' and selected_index is not None:
            try:
                dmg = int(values['-HP_CHANGE-'])
                c = self.combatants[selected_index]
                current_hp = int(c.hp or 0)
                c.hp = str(max(0, current_hp - dmg))
                if c.hp == "0" and "Down" not in c.conditions:
                    c.conditions.append("Down")
                self.refresh_table(selected_index)
            except ValueError:
                sg.popup("Invalid damage value")

        elif event == 'Heal' and selected_index is not None:
            try:
                heal = int(values['-HP_CHANGE-'])
                c = self.combatants[selected_index]
                current_hp = int(c.hp or 0)
                c.hp = str(current_hp + heal)
                if int(c.hp) > 0 and "Down" in c.conditions:
                    c.conditions.remove("Down")
                self.refresh_table(selected_index)
            except ValueError:
                sg.popup("Invalid heal value")

        elif event == '⏭ Next Char':
            self.next()
            active = self.get_active()
            if active:
                self.send_to_map(f"{active.name} active")
            self.window['-TURN-'].update(str(self.turn))
            self.refresh_table()

        elif event == '⏮ Prev Char':
            self.previous()
            active = self.get_active()
            if active:
                self.send_to_map(f"{active.name} active")
            self.window['-TURN-'].update(str(self.turn))
            self.refresh_table()

        elif event == '💾 Export':
            import datetime, os
            path = os.path.join(dir_path, f'Data/combat_tracker_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
            self.save_to_file(path)
            sg.popup(f"Saved to {path}")

        elif event == '📂 Load':
            file_path = sg.popup_get_file("Select tracker file", initial_folder=dir_path + "Data", file_types=(("JSON Files", "*.json"),))
            if file_path:
                self.load_from_file(file_path)
                self.window['-TURN-'].update(str(self.turn))
                selected_index = None
                selected_index_ref[0] = None
                self.send_to_map("CLEAR_SELECTION")
                self.refresh_table()


    def run_gui(self, dir_path):
        layout = self.build_gui_layout()
        self.window = sg.Window('D&D Initiative Tracker', layout, resizable=True, finalize=True)
    
        selected_index = [None]

        self.refresh_table()

        while True:
            event, values = self.window.read()
            if event == sg.WIN_CLOSED:
                break
            self.handle_event(event, values, selected_index, dir_path)

        self.window.close()

