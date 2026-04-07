"""WebSocket connection manager with fan-out to multiple clients."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections grouped by subscription key (e.g., event_ticker)."""

    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, key: str, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            if key not in self._connections:
                self._connections[key] = set()
            self._connections[key].add(ws)
        logger.info("WS connected: key=%s, total=%d", key, len(self._connections[key]))

    async def disconnect(self, key: str, ws: WebSocket):
        async with self._lock:
            conns = self._connections.get(key)
            if conns:
                conns.discard(ws)
                if not conns:
                    del self._connections[key]
        logger.info("WS disconnected: key=%s", key)

    async def broadcast(self, key: str, message: dict[str, Any]):
        """Send a JSON message to all clients subscribed to a key."""
        async with self._lock:
            conns = self._connections.get(key)
            if not conns:
                return
            clients = list(conns)

        payload = json.dumps(message)
        stale = []
        for ws in clients:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)

        if stale:
            async with self._lock:
                conns = self._connections.get(key)
                if conns:
                    for ws in stale:
                        conns.discard(ws)

    def subscriber_count(self, key: str) -> int:
        return len(self._connections.get(key, set()))

    def active_keys(self) -> list[str]:
        return list(self._connections.keys())
