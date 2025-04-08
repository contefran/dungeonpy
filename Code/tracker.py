import PySimpleGUI as sg
import numpy as np
import json
import os
import tempfile
import datetime
import sys

dir_path='C:/Users/Francesco/Desktop/Dnd_py/'

import sys
import json

initiative_data = []
selected_index = None
active_index = 0
turn = 1

# All D&D conditions + "Down"
conditions_list = [
    'Blinded', 'Charmed', 'Deafened', 'Frightened', 'Grappled',
    'Incapacitated', 'Invisible', 'Paralyzed', 'Petrified', 'Poisoned',
    'Prone', 'Restrained', 'See invisible', 'Stunned', 'Unconscious', 'Down'
]

# Condition icon mapping
condition_icons = {
    'Blinded': '🙈', 'Charmed': '💘', 'Deafened': '🙉', 'Frightened': '😱',
    'Grappled': '🤼', 'Incapacitated': '💤', 'Invisible': '👻', 'Paralyzed': '🧊',
    'Petrified': '🪨', 'Poisoned': '🩸', 'Prone': '🛌', 'Restrained': '⛓️',
    'See invisible': '👁️', 'Stunned': '😵', 'Unconscious': '🛑', 'Down': '💀'
}

# Font size for all elements
font_size = 12

def chunk(lst, size):
    return [lst[i:i + size] for i in range(0, len(lst), size)]

condition_rows = [
    [sg.Checkbox(f"{condition_icons[cond]} {cond}", key=f'-COND_{cond}-', font=('Segoe UI Emoji', font_size))
     for cond in chunk_row]
    for chunk_row in chunk(conditions_list, 5)
]

layout = [
    [sg.Text('Initiative Tracker', font=('Helvetica', font_size))],
    [sg.Table(values=[], headings=['Name', 'Initiative', 'HP', 'Conditions'],
                  auto_size_columns=False, justification='left', col_widths=[20, 10, 10, 20],
                  key='-TABLE-', enable_events=True, row_height=25, expand_x=True, num_rows=10,
                  background_color='white', text_color='black', font=('Segoe UI Emoji', font_size))],
    [sg.Text('Turn:', font=('Segoe UI Emoji', font_size)), sg.Input('1', key='-TURN-', size=(5, 1), font=('Segoe UI Emoji', font_size)),
     sg.Button('⏮ Prev Char', font=('Segoe UI Emoji', font_size)), sg.Button('⏭ Next Char', font=('Segoe UI Emoji', font_size))],
    [sg.HorizontalSeparator()],
    [sg.Text('Name', size=(10, 1), font=('Segoe UI Emoji', font_size)), sg.Input(key='-NAME-', size=(30, 1), font=('Segoe UI Emoji', font_size))],
    [sg.Text('Initiative', size=(10, 1), font=('Segoe UI Emoji', font_size)), sg.Input(key='-INITIATIVE-', size=(5, 1), font=('Segoe UI Emoji', font_size))],
    [sg.Text('HP (optional):', size=(12, 1), font=('Segoe UI Emoji', font_size)), sg.Input(key='-HP-', size=(5, 1), font=('Segoe UI Emoji', font_size)),
     sg.Text('   Change:', font=('Segoe UI Emoji', font_size)), sg.Input('0', key='-HP_CHANGE-', size=(5, 1), font=('Segoe UI Emoji', font_size)),
     sg.Button('Wound', font=('Segoe UI Emoji', font_size)), sg.Button('Heal', font=('Segoe UI Emoji', font_size))],
    [sg.Text('Conditions:', font=('Segoe UI Emoji', font_size))],
    *condition_rows,
    [
        sg.Button('Add New', font=('Segoe UI Emoji', font_size)), sg.Button('Update Selected', font=('Segoe UI Emoji', font_size)),
        sg.Button('Delete Selected', font=('Segoe UI Emoji', font_size)), sg.Button('↑ Move Up', font=('Segoe UI Emoji', font_size)),
        sg.Button('↓ Move Down', font=('Segoe UI Emoji', font_size))
    ],
    [sg.Button('💾 Export', font=('Segoe UI Emoji', font_size)), sg.Button('📂 Load', font=('Segoe UI Emoji', font_size))]

]

window = sg.Window('D&D Initiative Tracker', layout, resizable=True, finalize=True)

def refresh_table():
    table_data = []
    row_colors = []
    # Add a blank row at the top
    table_data.append(['', '', '', '', ''])  # Blank row

    for idx, c in enumerate(initiative_data):
        cond_icons = ''.join(condition_icons[cond] for cond in c['conditions'])
        hp = c.get('hp', '')
        pos = c.get('pos', '—')
        pos_str = f" ({pos[0]},{pos[1]})" if isinstance(pos, (list, tuple)) else ' —'

        # Show ➡️ only for the active turn character
        name_display = f"➡️ {c['name']}" if idx == active_index else c['name']
        table_data.append([name_display, c['initiative'], hp, cond_icons, pos_str])

        # Row colouring
        if 'Down' in c['conditions']:
            row_colors.append((idx +1, 'gray'))
        elif idx == active_index:
            row_colors.append((idx +1, '#ccf2ff'))
        else:
            row_colors.append((idx +1, 'white'))

    window['-TABLE-'].update(values=table_data, row_colors=row_colors)

    if selected_index is not None and 0 <= selected_index < len(initiative_data):
        window['-TABLE-'].update(select_rows=[selected_index+1]) # Adjust for the blank row
    else:
        window['-TABLE-'].update(select_rows=[])

# Check if a tracker file is provided as a command-line argument
if len(sys.argv) > 1:
    tracker_file_path = sys.argv[1]
    try:
        with open(tracker_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f"Loaded tracker data from {tracker_file_path}")
        # Populate initiative_data and refresh the table
        initiative_data.clear()
        initiative_data.extend(data.get('initiative', []))
        active_index = data.get('active_index', 0)
        turn = data.get('turn', 1)
        refresh_table()
        window['-TURN-'].update(str(turn))
        # Use `data` to populate the tracker table
    except Exception as e:
        print(f"Error loading tracker file: {e}")
else:
    print("No tracker file provided.")

while True:
    event, values = window.read()
    if event == sg.WIN_CLOSED:
        break

    if event == 'Add New':
        try:
            # Create new entry with empty fields including icon
            new_entry = {
                'name': values['-NAME-'],
                'initiative': int(values['-INITIATIVE-']),
                'hp': values['-HP-'],
                'conditions': [],
                'pos': None,
                'icon': None
            }
            initiative_data.append(new_entry)
            initiative_data.sort(key=lambda x: x['initiative'], reverse=True)
            selected_index = 0
            refresh_table()
            for cond in conditions_list:
                window[f'-COND_{cond}-'].update(False)
        except ValueError:
            sg.popup('Invalid initiative value. Please enter a valid number.')

    elif event == '-TABLE-':
        try:
            if values['-TABLE-']:
                selected_index = values['-TABLE-'][0] -1 # Adjust for the blank row
                if selected_index == -1:  # Blank row clicked
                    selected_index = None
                    window['-NAME-'].update('')
                    window['-INITIATIVE-'].update('')
                    window['-HP-'].update('')
                    for cond in conditions_list:
                        window[f'-COND_{cond}-'].update(False)
                    window['-TABLE-'].update(select_rows=[])
                else:
                    entry = initiative_data[selected_index]
                    window['-NAME-'].update(entry['name'])
                    window['-INITIATIVE-'].update(entry['initiative'])
                    window['-HP-'].update(entry.get('hp', ''))
                    for cond in conditions_list:
                        window[f'-COND_{cond}-'].update(cond in entry['conditions'])
            else:
                selected_index = None
        except IndexError:
            selected_index = None

    elif event == 'Update Selected' and selected_index is not None:
        current = initiative_data[selected_index]
        updated_conditions = [
            cond for cond in conditions_list if values.get(f'-COND_{cond}-', False)
        ]
    
        initiative_data[selected_index] = {
            'name': values['-NAME-'],
            'initiative': int(values['-INITIATIVE-']),
            'hp': values['-HP-'],
            'conditions': updated_conditions,
            'pos': current.get('pos'),
            'icon': current.get('icon')  # ✅ keep existing icon
        }
        refresh_table()

    elif event == 'Delete Selected' and selected_index is not None:
        initiative_data.pop(selected_index)
        selected_index = None
        refresh_table()

    elif event == '↑ Move Up' and selected_index is not None:
        if selected_index > 0:  # Ensure we don't try to move the first row (after the blank row)
            initiative_data[selected_index], initiative_data[selected_index - 1] = \
                initiative_data[selected_index - 1], initiative_data[selected_index]
            selected_index -= 1
            refresh_table()
            window['-TABLE-'].update(select_rows=[selected_index + 1])  # Adjust for the blank row

    elif event == '↓ Move Down' and selected_index is not None:
        if selected_index < len(initiative_data) - 1:  # Ensure we don't try to move the last row
            initiative_data[selected_index], initiative_data[selected_index + 1] = \
                initiative_data[selected_index + 1], initiative_data[selected_index]
            selected_index += 1
            refresh_table()
            window['-TABLE-'].update(select_rows=[selected_index + 1])  # Adjust for the blank row

    elif event == 'Wound' and selected_index is not None:
        try:
            dmg = int(values['-HP_CHANGE-'])
            current_hp = int(initiative_data[selected_index].get('hp') or 0)
            new_hp = max(0, current_hp - dmg)
            initiative_data[selected_index]['hp'] = str(new_hp)

            # Add "Down" condition if HP hits 0
            conditions = initiative_data[selected_index]['conditions']
            if new_hp == 0 and 'Down' not in conditions:
                conditions.append('Down')
            refresh_table()
        except ValueError:
            sg.popup('Invalid damage value.')

    elif event == 'Heal' and selected_index is not None:
        try:
            heal = int(values['-HP_CHANGE-'])
            current_hp = int(initiative_data[selected_index].get('hp') or 0)
            new_hp = current_hp + heal
            initiative_data[selected_index]['hp'] = str(new_hp)

            # Remove "Down" condition if HP goes above 0
            conditions = initiative_data[selected_index]['conditions']
            if new_hp > 0 and 'Down' in conditions:
                conditions.remove('Down')
            refresh_table()
        except ValueError:
            sg.popup('Invalid heal value.')

    elif event == '⏭ Next Char':
        if initiative_data:
            active_index = (active_index + 1) % len(initiative_data)
            if active_index == 0:
                turn += 1
            window['-TURN-'].update(str(turn))
            refresh_table()

    elif event == '⏮ Prev Char':
        if initiative_data:
            active_index = (active_index - 1) % len(initiative_data)
            if active_index < 1:
                active_index = len(initiative_data) - 1
                turn = max(1, turn - 1)
            window['-TURN-'].update(str(turn))
            refresh_table()

    elif event == '💾 Export':
        import json
        import os
        data = {
            'turn': turn,
            'active_index': selected_index,
            'initiative': initiative_data
        }
        # Determine a cross-platform temp file path
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename = f'Data/combat_tracker_{timestamp}.json'
        temp_path = os.path.join(dir_path, filename)
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            sg.popup(f'Data exported to:\n{temp_path}')
        except Exception as e:
            sg.popup(f'Error saving file:\n{e}')

    elif event == '📂 Load':
        file_list = [f for f in os.listdir(dir_path+"Data/") if f.startswith('combat_tracker_') and f.endswith('.json')]
        if not file_list:
            sg.popup('No saved combat trackers found.')
        else:
            selected_file = sg.popup_get_file('Select a tracker to load:', initial_folder=dir_path+"Data/", file_types=(("JSON Files", "*.json"),), no_window=True)
            if selected_file:
                try:
                    with open(selected_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    initiative_data.clear()
                    initiative_data.extend(data.get('initiative', []))
                    active_index = data.get('active_index', 0)
                    turn = data.get('turn', 1)
                    window['-TURN-'].update(str(turn))
                    selected_index = None
                    refresh_table()
                    sg.popup(f'Data loaded from:\n{selected_file}')
                except Exception as e:
                    sg.popup(f'Error loading file:\n{e}')

window.close()
