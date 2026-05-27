"""
ui/ws_bridge.py — Lightweight WebSocket server that bridges JARVIS Python
backend to the glassmorphic HUD overlay (index.html).

Usage (start alongside main.py):
    python ui/ws_bridge.py          # Default port 8000

Or import and call from main.py:
    from ui.ws_bridge import JarvisUIBridge
    bridge = JarvisUIBridge()
    bridge.start_in_thread()
    bridge.update_state("LISTENING")
    bridge.show_weather_card({"city":"Sonipat","temp":32,...})

Protocol (server → client JSON):
  {"type":"state","value":"IDLE|LISTENING|THINKING|SPEAKING"}
  {"type":"card","cardType":"WEATHER","data":{...}}
  {"type":"card","cardType":"REMINDERS","data":{"reminders":[...]}}
  {"type":"card","cardType":"SCREENSHOT","data":{"filename":"...","path":"..."}}
  {"type":"transcript","speaker":"JARVIS","text":"..."}
  {"type":"close_panel"}

Protocol (client → server JSON):
  {"type":"command","text":"open notepad"}
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Callable, Optional, Set

logger = logging.getLogger(__name__)

# ── Optional websockets dependency ──────────────────────────────────────────
try:
    import websockets                          # type: ignore
    import websockets.server as _ws_server    # type: ignore
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False
    logger.warning(
        "websockets package not found — UI bridge disabled. "
        "Install it:  pip install websockets"
    )


class JarvisUIBridge:
    """
    Thread-safe WebSocket server that pushes state updates from the Python
    JARVIS core to the browser HUD overlay.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        on_command: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Args:
            host:       Bind address (keep as localhost for security).
            port:       WebSocket port (must match ws://localhost:<port> in app.js).
            on_command: Callback invoked when the UI sends a text command.
                        Signature: on_command(text: str)
        """
        self._host       = host
        self._port       = port
        self._on_command = on_command
        self._clients:  Set[Any] = set()
        self._loop:     Optional[asyncio.AbstractEventLoop] = None
        self._thread:   Optional[threading.Thread] = None
        self._running   = False

    # ── Start / stop ──────────────────────────────────────────────────────────

    def start_in_thread(self) -> None:
        """Start the WS server in a background daemon thread."""
        if not _WS_AVAILABLE:
            logger.warning("JarvisUIBridge: websockets not installed — skipping.")
            return
        if self._running:
            return

        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="JARVIS-UI-WSBridge",
        )
        self._thread.start()
        logger.info("JarvisUIBridge started on ws://%s:%d", self._host, self._port)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._running = True
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as exc:
            logger.error("JarvisUIBridge loop error: %s", exc)
        finally:
            self._running = False

    async def _serve(self) -> None:
        async with websockets.serve(self._handler, self._host, self._port):
            logger.info("WS Bridge: listening on ws://%s:%d", self._host, self._port)
            await asyncio.Future()   # run forever until cancelled

    # ── Client handler ────────────────────────────────────────────────────────

    async def _handler(self, websocket: Any, path: str = "/") -> None:
        self._clients.add(websocket)
        addr = websocket.remote_address
        logger.info("WS Client connected: %s  (total: %d)", addr, len(self._clients))
        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                    await self._on_client_message(msg)
                except json.JSONDecodeError:
                    logger.debug("WS: non-JSON from client: %s", raw[:80])
        except Exception as exc:
            logger.debug("WS client %s disconnected: %s", addr, exc)
        finally:
            self._clients.discard(websocket)
            logger.info("WS Client disconnected: %s  (total: %d)", addr, len(self._clients))

    async def _on_client_message(self, msg: dict) -> None:
        """Route messages received from the UI."""
        mtype = msg.get("type", "")
        if mtype == "command":
            text = msg.get("text", "").strip()
            logger.info("UI command received: '%s'", text)
            if text and self._on_command:
                # Dispatch on calling thread (thread-safe call into JARVIS core)
                threading.Thread(
                    target=self._on_command,
                    args=(text,),
                    daemon=True,
                ).start()

    # ── Broadcast helpers (thread-safe, call from any thread) ─────────────────

    def _broadcast(self, payload: dict) -> None:
        """Thread-safe broadcast to all connected clients."""
        if not self._loop or not self._clients:
            return
        raw = json.dumps(payload)
        asyncio.run_coroutine_threadsafe(self._async_broadcast(raw), self._loop)

    async def _async_broadcast(self, raw: str) -> None:
        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send(raw)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    # ── Public API ────────────────────────────────────────────────────────────

    def update_state(self, state: str) -> None:
        """
        Push a state change to the HUD visualizer.
        state must be one of: 'IDLE', 'LISTENING', 'THINKING', 'SPEAKING'
        """
        self._broadcast({"type": "state", "value": state.upper()})

    def add_transcript(self, speaker: str, text: str) -> None:
        """
        Append a line to the HUD transcript display.
        speaker: 'JARVIS' or 'You'
        """
        self._broadcast({"type": "transcript", "speaker": speaker, "text": text})

    def show_weather_card(self, data: dict) -> None:
        """
        Open the weather info card.
        data keys: city, temp, feels, condition, icon, humidity, wind, visibility,
                   forecast: [{"label": "Now", "temp": 32}, ...]
        """
        self._broadcast({"type": "card", "cardType": "WEATHER", "data": data})

    def show_reminders_card(self, reminders: list) -> None:
        """
        Open the reminders card.
        reminders: [{"id": 1, "text": "...", "time": "3:00 PM", "due": False}, ...]
        """
        self._broadcast({
            "type": "card",
            "cardType": "REMINDERS",
            "data": {"reminders": reminders},
        })

    def show_screenshot_card(self, filename: str, path: str = "", url: str = "") -> None:
        """
        Open the screenshot card.
        filename: basename of the saved screenshot file.
        url: optional file:// or http:// URL for the thumbnail image.
        """
        from datetime import datetime
        self._broadcast({
            "type": "card",
            "cardType": "SCREENSHOT",
            "data": {
                "filename":  filename,
                "path":      path,
                "url":       url,
                "timestamp": datetime.now().strftime("%I:%M %p"),
            },
        })

    def hide_panel(self) -> None:
        """Close the slide-out info panel."""
        self._broadcast({"type": "close_panel"})

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def client_count(self) -> int:
        return len(self._clients)


# ── Global bridge instance ────────────────────────────────────────────────────
ui_bridge = JarvisUIBridge()


# ── Standalone test server ────────────────────────────────────────────────────

if __name__ == "__main__":
    import time, sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    )

    if not _WS_AVAILABLE:
        print("ERROR: Please install websockets:  pip install websockets")
        sys.exit(1)

    def on_cmd(text: str) -> None:
        print(f"[TEST] UI sent command: '{text}'")

    bridge = JarvisUIBridge(on_command=on_cmd)
    bridge.start_in_thread()
    time.sleep(1.0)   # let server bind

    print("\nJARVIS UI Bridge running at ws://localhost:8000")
    print("Open ui/index.html in a browser to connect.")
    print("Demo cycle will run for 30 seconds...\n")

    # Demo cycle — mirrors the JS _runDemoCycle()
    states = [
        (1.5,  "LISTENING"),
        (5.0,  "THINKING"),
        (8.0,  "SPEAKING"),
        (12.0, "SPEAKING"),  # card shown
        (16.0, "IDLE"),
        (20.0, "SPEAKING"),  # reminders card
        (26.0, "IDLE"),
    ]
    for delay, state in states:
        time.sleep(delay if delay <= 5 else delay - sum(d for d,_ in states if d < delay) + 0.1)
        bridge.update_state(state)
        print(f"→ State: {state}")
        if delay == 12.0:
            bridge.show_weather_card({
                "city": "Sonipat", "temp": 32, "feels": 34,
                "condition": "Partly Cloudy", "icon": "⛅",
                "humidity": 62, "wind": 18, "visibility": "8 km",
                "forecast": [
                    {"label": "Now",  "temp": 32},
                    {"label": "+3h",  "temp": 35},
                    {"label": "+6h",  "temp": 30},
                    {"label": "+9h",  "temp": 27},
                    {"label": "+12h", "temp": 25},
                ],
            })
        if delay == 20.0:
            bridge.show_reminders_card([
                {"id": 1, "text": "Team standup",    "time": "10:00 AM", "due": False},
                {"id": 2, "text": "Drink water",     "time": "10:30 AM", "due": True},
                {"id": 3, "text": "Review PR #42",   "time": "02:00 PM", "due": False},
            ])

    print("\nDemo complete. Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down.")
