"""
chat_window.py — DM-side chat window.

One tab per PC (combatants flagged is_pc=True).  Tabs are rebuilt whenever
the PC roster changes; history is preserved across rebuilds.

The window is opened/closed by the Tracker's Toggle Chat button and lives
independently on screen.  Events are handled through sg.read_all_windows()
in the Tracker's main event loop.
"""

import sys

import PySimpleGUI as sg


_UI_FONT = 'Segoe UI' if sys.platform == 'win32' else 'gothic'
_FONT      = (_UI_FONT, 12)
_FONT_BOLD = (_UI_FONT, 12, 'bold')


class ChatWindow:

    def __init__(self, submit_fn):
        self._submit = submit_fn
        # pc_name → list of display lines, e.g. ["DM: watch out", "Alice: ok"]
        self._history: dict[str, list[str]] = {}
        self._pc_names: list[str] = []   # current tab order
        self.window: sg.Window | None = None
        self._unread: set[str] = set()   # pc names with unread inbound messages
        self._ping_fn = None             # injected by Game; called on inbound message

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self, pc_names: list[str]):
        """Open (or reopen) the chat window with one tab per PC name."""
        if self.window:
            self.window.close()
        self._pc_names = list(pc_names)
        self._current_tab: str | None = pc_names[0] if pc_names else None
        self.window = self._build_window()

    def close(self):
        if self.window:
            self.window.close()
            self.window = None

    def rebuild(self, pc_names: list[str]):
        """Rebuild tabs when the PC roster changes (preserves history)."""
        if self.window:
            self.open(pc_names)

    def is_open(self) -> bool:
        return self.window is not None

    # ------------------------------------------------------------------
    # Building the window
    # ------------------------------------------------------------------

    def _build_window(self) -> sg.Window:
        if not self._pc_names:
            layout = [
                [sg.Text('No player characters yet.',  font=_FONT)],
                [sg.Text('Add combatants and flag them as PC.', font=_FONT)],
            ]
        else:
            tabs = []
            for name in self._pc_names:
                history_text = "\n".join(self._history.get(name, []))
                tab_layout = [
                    [sg.Multiline(
                        history_text,
                        key=f'-LOG_{name}-',
                        expand_x=True, expand_y=True,
                        disabled=True, autoscroll=True,
                        font=_FONT,
                    )],
                    [
                        sg.Input(key=f'-INPUT_{name}-', expand_x=True, font=_FONT),
                        sg.Button('Send', key=f'-SEND_{name}-'),
                    ],
                ]
                tabs.append(sg.Tab(name, tab_layout, key=f'-TAB_{name}-'))
            layout = [
                [sg.TabGroup([tabs], key='-TABS-', enable_events=True,
                             expand_x=True, expand_y=True, font=_FONT_BOLD)],
            ]

        win = sg.Window(
            'DM Chat',
            layout,
            resizable=True,
            finalize=True,
            size=(420, 480),
        )
        for name in self._pc_names:
            win[f'-INPUT_{name}-'].bind('<Return>', '_RETURN')
        return win

    # ------------------------------------------------------------------
    # Event handling (called from Tracker's read_all_windows loop)
    # ------------------------------------------------------------------

    def _update_title(self):
        if not self.window:
            return
        title = f'DM Chat  ●  {", ".join(sorted(self._unread))}' if self._unread else 'DM Chat'
        try:
            self.window.TKroot.title(title)
        except Exception:
            pass

    def mark_current_tab_read(self):
        """Clear the unread indicator for whichever tab is currently visible."""
        if self._current_tab:
            self._unread.discard(self._current_tab)
            self._update_title()

    def handle_event(self, event, values) -> bool:
        """
        Process one event from this window.
        Returns False if the window was closed (caller should update button label).
        """
        if event in (sg.WIN_CLOSED, sg.WINDOW_CLOSE_ATTEMPTED_EVENT):
            self.window.close()
            self.window = None
            return False

        # Tab switched — clear unread for the newly visible tab only
        if event == '-TABS-':
            self._current_tab = values.get('-TABS-')
            if self._current_tab:
                self._unread.discard(self._current_tab)
                self._update_title()

        for name in self._pc_names:
            if event in (f'-SEND_{name}-', f'-INPUT_{name}-_RETURN'):
                text = (values.get(f'-INPUT_{name}-') or '').strip()
                if text:
                    self._submit({"action": "chat_message", "to": name, "text": text})
                    self.window[f'-INPUT_{name}-'].update('')
                self._unread.discard(name)   # clear this tab's notification only
                self._update_title()
                break

        return True

    # ------------------------------------------------------------------
    # Incoming messages
    # ------------------------------------------------------------------

    def receive(self, pc_name: str, sender: str, text: str):
        """
        Add a message to a PC's log.
        Called by the Tracker on the GUI thread when a chat_message event arrives.
        pc_name: which tab to update (Alice's tab for messages to/from Alice).
        sender:  display name ("DM" or the player's name).
        """
        line = f"{sender}: {text}"
        self._history.setdefault(pc_name, []).append(line)
        if self.window:
            try:
                key = f'-LOG_{pc_name}-'
                current = self.window[key].get()
                updated = (current.rstrip('\n') + '\n' + line).lstrip('\n')
                self.window[key].update(updated)
            except Exception:
                pass
        # Notify DM of inbound player message
        if sender != "DM":
            self._unread.add(pc_name)
            self._update_title()
            if self._ping_fn:
                self._ping_fn()
