"""
WebSocket bridge — exposes the authoritative GameServer over ws://<host>:<port>.

All intents (from WS clients AND from in-process GUI threads) funnel through a
single asyncio.Queue and are processed sequentially on the asyncio event loop
thread, eliminating shared-state races without any explicit locking.

Flow
----
  GUI thread  ──► ws_bridge.submit(intent)          ──► asyncio.Queue ──►┐
  WS client   ──► handler receives JSON intent      ──► asyncio.Queue ──►├──► process_loop
                                                                           │         │
                                                                           │         ▼
                                                                           │   server.submit(intent)
                                                                           │         │
                                                                           │    calls in-process
                                                                           │    subscribers + _on_server_event
                                                                           │         │
                                                                           └─────────▼
                                                                        _broadcast(event) → all WS clients
"""

import asyncio
import json
import threading

import websockets


class WSBridge:

    def __init__(self, server, host: str = 'localhost', port: int = 8765):
        self.server = server
        self.host = host
        self.port = port           # updated to actual OS-assigned port after start()
        self._connections: set = set()
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
        The threading.Event acts as a memory barrier, so self._loop and
        self._queue are guaranteed to be visible after this call returns.
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
        async with websockets.serve(self._handler, self.host, self.port) as srv:
            # If port=0 was passed, record the OS-assigned ephemeral port
            self.port = srv.sockets[0].getsockname()[1]
            ready.set()
            process_task = asyncio.create_task(self._process_loop())
            await self._stop_event.wait()
            process_task.cancel()
            try:
                await process_task
            except asyncio.CancelledError:
                pass
        # async with exits cleanly here, closing the server socket

    def stop(self):
        """Signal the WS server to shut down gracefully."""
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    # ------------------------------------------------------------------
    # Per-connection handler
    # ------------------------------------------------------------------

    async def _handler(self, ws):
        self._connections.add(ws)
        try:
            # Immediately send full state so the new client is in sync
            await ws.send(json.dumps(self.server.get_snapshot()))
            async for raw in ws:
                try:
                    intent = json.loads(raw)
                    await self._queue.put(intent)
                except (json.JSONDecodeError, TypeError):
                    pass  # ignore malformed frames
        finally:
            self._connections.discard(ws)

    # ------------------------------------------------------------------
    # Single intent-processing loop — runs on the asyncio thread
    # ------------------------------------------------------------------

    async def _process_loop(self):
        """
        Dequeue one intent at a time and process it synchronously.
        Because this is the only place server.submit() is ever called,
        there are no concurrent mutations of server state — no locking needed.
        """
        while True:
            intent = await self._queue.get()
            try:
                # server.submit() is synchronous and fast (pure in-memory ops).
                # It calls _on_server_event for each emitted event, which schedules
                # _broadcast tasks that run on the next loop iteration.
                self.server.submit(intent)
            except Exception as e:
                # A subscriber callback threw (e.g. GUI window not yet ready).
                # Log and continue — never let a single bad intent kill the loop.
                print(f"[WSBridge] Error processing intent {intent.get('action')!r}: {e}")

    # ------------------------------------------------------------------
    # Server event → WS broadcast
    # ------------------------------------------------------------------

    def _on_server_event(self, event: dict):
        """
        Sync callback registered with server.subscribe().
        Always called on the asyncio thread (from within _process_loop),
        so create_task() is safe here.
        """
        self._loop.create_task(self._broadcast(json.dumps(event)))

    async def _broadcast(self, message: str):
        if not self._connections:
            return
        results = await asyncio.gather(
            *(ws.send(message) for ws in list(self._connections)),
            return_exceptions=True,
        )
        # Prune any connections that raised (closed / broken pipe)
        for ws, result in zip(list(self._connections), results):
            if isinstance(result, Exception):
                self._connections.discard(ws)

    # ------------------------------------------------------------------
    # Thread-safe submit — called from GUI threads (Tracker, MapManager)
    # ------------------------------------------------------------------

    def submit(self, intent: dict):
        """Queue an intent from any thread. Returns immediately."""
        asyncio.run_coroutine_threadsafe(self._queue.put(intent), self._loop)
