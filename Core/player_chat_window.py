"""
player_chat_window.py — Player-side chat window.

A single-pane chat log (no tabs — the player only talks to the DM).
Runs on the main thread via its own event loop.  The map runs on a daemon
thread, so when this window closes the whole process exits cleanly.
"""

import threading
import PySimpleGUI as sg


_FONT = ('Helvetica', 12)


class PlayerChatWindow:

    def __init__(self, player_name: str, submit_fn):
        self.player_name = player_name
        self._submit = submit_fn
        self._history: list[str] = []
        self.window: sg.Window | None = None

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_window(self) -> sg.Window:
        history_text = "\n".join(self._history)
        layout = [
            [sg.Multiline(
                history_text,
                key='-LOG-',
                expand_x=True, expand_y=True,
                disabled=True, autoscroll=True,
                font=_FONT,
            )],
            [
                sg.Input(key='-INPUT-', expand_x=True, font=_FONT),
                sg.Button('Send', key='Send'),
            ],
        ]
        win = sg.Window(
            f'Chat — {self.player_name}',
            layout,
            resizable=True,
            finalize=True,
            size=(350, 400),
        )
        win['-INPUT-'].bind('<Return>', '_RETURN')
        return win

    # ------------------------------------------------------------------
    # Main loop — runs on the main thread
    # ------------------------------------------------------------------

    def run(self, quit_event: threading.Event):
        """
        Block until the window is closed or quit_event is set (e.g. map closed).
        Uses a timeout so it stays responsive to quit_event.
        """
        self.window = self._build_window()

        while not quit_event.is_set():
            event, values = self.window.read(timeout=200)

            if event == sg.WIN_CLOSED:
                quit_event.set()   # chat close = app quit
                break

            if event in ('Send', '-INPUT-_RETURN'):
                text = (values.get('-INPUT-') or '').strip()
                if text:
                    self._submit({"action": "chat_message", "text": text})
                    self._append(f"You: {text}")
                    self.window['-INPUT-'].update('')

            elif event == 'SERVER_EVENT':
                chat_event = values.get(event, {})
                if chat_event.get("action") == "chat_message":
                    sender = chat_event.get("from", "DM")
                    text   = chat_event.get("text", "")
                    self._append(f"{sender}: {text}")

        self.window.close()
        self.window = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _append(self, line: str):
        self._history.append(line)
        if self.window:
            current = self.window['-LOG-'].get()
            updated = (current.rstrip('\n') + '\n' + line).lstrip('\n')
            self.window['-LOG-'].update(updated)

    def handle_server_event(self, event: dict):
        """Called from the player_client subscriber thread — posts to GUI queue."""
        if self.window:
            self.window.write_event_value('SERVER_EVENT', event)

    def close(self):
        """Signal the run() loop to exit (called from another thread)."""
        # quit_event.set() is the clean way; this is just a belt-and-suspenders flag
        if self.window:
            try:
                self.window.write_event_value(sg.WIN_CLOSED, None)
            except Exception:
                pass
