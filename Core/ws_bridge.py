"""
WebSocket bridge — exposes the authoritative GameServer over ws(s)://<host>:<port>.

All intents funnel through a single asyncio.Queue and are processed sequentially
on the asyncio event loop thread, eliminating shared-state races without locking.

Handshake (every new connection must complete this before sending intents):

  Client → Server:  {"type": "hello", "role": "dm"|"player",
                      "name": "...", "password": "..."}   # password only for dm
  Server → Client:  {"type": "hello_ack", "ok": true, "role": "..."}
                 OR {"type": "hello_ack", "ok": false, "reason": "..."}  → connection closed
  Server → Client:  <initial snapshot>

Permission model:
  - DM connections (or in-process GUI submits): all intents allowed.
  - Player connections: only "select", "clear_selection", "move_token"
    (own token, and only when DM has unlocked that player).
  - If password is None on the server, DM role is accepted without a password
    (used for --mode both / local play / tests).

Queue items are (ws, intent) tuples.  ws=None means in-process (always allowed).
"""

import asyncio
import json
import threading

import websockets


class WSBridge:

    def __init__(self, server, host: str = 'localhost', port: int = 8765,
                 password: str | None = None, ssl_context=None):
        self.server = server
        self.host = host
        self.port = port           # updated to actual OS-assigned port after start()
        self._password = password
        self._ssl_context = ssl_context
        self._connections: set = set()
        self._clients: dict = {}   # ws → {"role": str, "name": str}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._stop_event: asyncio.Event | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """
        Start the WS server in a background daemon thread.
        Blocks until the server socket is bound and listening.
        """
        self.server.subscribe(self._on_server_event)
        ready = threading.Event()
        threading.Thread(
            target=self._run, args=(ready,), daemon=True, name='ws-bridge'
        ).start()
        ready.wait()

    def _run(self, ready: threading.Event):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._queue = asyncio.Queue()
        self._loop.run_until_complete(self._serve(ready))

    async def _serve(self, ready: threading.Event):
        self._stop_event = asyncio.Event()
        async with websockets.serve(
            self._handler, self.host, self.port, ssl=self._ssl_context
        ) as srv:
            self.port = srv.sockets[0].getsockname()[1]
            ready.set()
            process_task = asyncio.create_task(self._process_loop())
            await self._stop_event.wait()
            process_task.cancel()
            try:
                await process_task
            except asyncio.CancelledError:
                pass

    def stop(self):
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    # ------------------------------------------------------------------
    # Per-connection handler
    # ------------------------------------------------------------------

    async def _handler(self, ws):
        # Step 1: wait for hello (10 s timeout)
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            hello = json.loads(raw)
        except (asyncio.TimeoutError, json.JSONDecodeError,
                websockets.exceptions.ConnectionClosed):
            return

        if hello.get("type") != "hello":
            await ws.send(json.dumps(
                {"type": "hello_ack", "ok": False, "reason": "expected hello message"}))
            return

        role = hello.get("role", "player")
        name = hello.get("name", "Unknown")
        color = hello.get("color", "white")

        # Step 2: validate
        if role == "dm":
            if self._password and hello.get("password") != self._password:
                await ws.send(json.dumps(
                    {"type": "hello_ack", "ok": False, "reason": "wrong password"}))
                return
        elif role == "player":
            pass  # any name accepted
        else:
            await ws.send(json.dumps(
                {"type": "hello_ack", "ok": False,
                 "reason": f"unknown role '{role}'"}))
            return

        # Step 3: register + greet
        self._clients[ws] = {"role": role, "name": name, "color": color}
        self._connections.add(ws)
        await ws.send(json.dumps({"type": "hello_ack", "ok": True, "role": role}))
        await ws.send(json.dumps(self.server.get_snapshot()))

        # Step 4: notify DM tracker of player arrival
        if role == "player":
            await self._queue.put((None, {"action": "player_connected", "name": name}))

        # Step 5: normal intent loop
        try:
            async for raw in ws:
                try:
                    intent = json.loads(raw)
                    await self._queue.put((ws, intent))
                except (json.JSONDecodeError, TypeError):
                    pass
        finally:
            self._connections.discard(ws)
            self._clients.pop(ws, None)
            if role == "player":
                # Fire-and-forget: notify after handler exits
                self._loop.create_task(
                    self._queue.put((None, {"action": "player_disconnected", "name": name}))
                )

    # ------------------------------------------------------------------
    # Permission check
    # ------------------------------------------------------------------

    def _check_permission(self, ws, intent: dict) -> tuple[bool, str | None]:
        client = self._clients.get(ws)
        if client is None:
            return False, "not authenticated"
        if client["role"] == "dm":
            return True, None

        # Player rules
        action = intent.get("action")
        _PLAYER_ALLOWED = {"select", "clear_selection", "move_token"}
        if action not in _PLAYER_ALLOWED:
            return False, f"action '{action}' not permitted for players"
        locked = not self.server.player_locks.get(client["name"])
        if action == "select":
            if locked:
                return False, "map interaction not currently allowed — wait for the DM to enable you"
        if action == "move_token":
            if intent.get("name") != client["name"]:
                return False, "players may only move their own token"
            if locked:
                return False, "map interaction not currently allowed — wait for the DM to enable you"
        return True, None

    # ------------------------------------------------------------------
    # Single intent-processing loop
    # ------------------------------------------------------------------

    async def _process_loop(self):
        while True:
            ws, intent = await self._queue.get()
            # Permission check for WS-sourced intents (ws=None means in-process, always OK)
            if ws is not None:
                ok, reason = self._check_permission(ws, intent)
                if not ok:
                    err = json.dumps({"type": "error", "seq": 0, "reason": reason})
                    try:
                        await ws.send(err)
                    except Exception:
                        pass
                    continue
            # Inject selector identity into selection intents from WS clients
            if ws is not None:
                client = self._clients.get(ws)
                if client and intent.get("action") in ("select", "clear_selection"):
                    intent = dict(intent)
                    intent["selector"] = client["name"]
                    intent["color"] = client.get("color", "white")
            try:
                self.server.submit(intent)
            except Exception as e:
                print(f"[WSBridge] Error processing intent {intent.get('action')!r}: {e}")

    # ------------------------------------------------------------------
    # Server event → WS broadcast
    # ------------------------------------------------------------------

    def _on_server_event(self, event: dict):
        """Sync callback registered with server.subscribe(). Runs on the asyncio thread."""
        action = event.get("action")
        # Player join/leave notifications are DM-only — players don't need them and
        # receiving them mid-stream would confuse the response ordering in player clients.
        if action in ("player_connected", "player_disconnected"):
            self._loop.create_task(self._broadcast_dm_only(json.dumps(event)))
        else:
            self._loop.create_task(self._broadcast(json.dumps(event)))

    async def _broadcast(self, message: str):
        if not self._connections:
            return
        results = await asyncio.gather(
            *(ws.send(message) for ws in list(self._connections)),
            return_exceptions=True,
        )
        for ws, result in zip(list(self._connections), results):
            if isinstance(result, Exception):
                self._connections.discard(ws)

    async def _broadcast_dm_only(self, message: str):
        dm_connections = [ws for ws, info in self._clients.items()
                          if info.get("role") == "dm"]
        if not dm_connections:
            return
        await asyncio.gather(
            *(ws.send(message) for ws in dm_connections),
            return_exceptions=True,
        )

    # ------------------------------------------------------------------
    # Thread-safe submit — called from GUI threads (Tracker, MapManager)
    # ------------------------------------------------------------------

    def submit(self, intent: dict):
        """Queue an intent from any thread as a trusted (DM) in-process call."""
        asyncio.run_coroutine_threadsafe(
            self._queue.put((None, intent)), self._loop
        )
