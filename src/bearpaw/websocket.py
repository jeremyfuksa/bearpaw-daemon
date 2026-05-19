from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

from bearpaw.config import WebSocketConfig

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self, config: WebSocketConfig) -> None:
        self._config = config
        self._connections: Set[WebSocket] = set()
        self._last_pong: Dict[WebSocket, float] = {}
        self._last_ping: Dict[WebSocket, float] = {}
        self._topics: Dict[WebSocket, Optional[Set[str]]] = {}
        # Per-connection "live" flag. Default True preserves the pre-1.4
        # contract where any subscriber forced fast STS polling. Clients
        # that don't need 10 Hz state updates can send
        # {"type": "subscribe", "topics": [...], "live": false} so the
        # daemon stays on idle_sts_interval. See issue #16.
        self._live: Dict[WebSocket, bool] = {}

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        logger.info(
            "Client connected, total connections: %d", len(self._connections) + 1
        )
        self._connections.add(websocket)
        self._last_pong[websocket] = time.time()
        self._topics[websocket] = None
        self._live[websocket] = True

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)
        self._last_pong.pop(websocket, None)
        self._last_ping.pop(websocket, None)
        self._topics.pop(websocket, None)
        self._live.pop(websocket, None)

    async def broadcast(self, message: dict, force: bool = False) -> None:
        topic = _topic_for_message(message) if not force else None
        for websocket in list(self._connections):
            if topic and not self._is_subscribed(websocket, topic):
                continue
            try:
                await websocket.send_json(message)
            except Exception:
                logger.warning("WebSocket send failed; dropping client", exc_info=True)
                self.disconnect(websocket)

    async def heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self._config.ping_interval)
            now = time.time()
            for websocket in list(self._connections):
                last_ping = self._last_ping.get(websocket)
                last_pong = self._last_pong.get(websocket, 0)
                if (
                    last_ping
                    and last_pong < last_ping
                    and now - last_ping > self._config.ping_timeout
                ):
                    self.disconnect(websocket)
                    try:
                        await websocket.close(code=1001)
                    except Exception:
                        pass
                    continue
                try:
                    await websocket.send_json({"type": "ping"})
                    self._last_ping[websocket] = now
                except Exception:
                    self.disconnect(websocket)

    async def handle_messages(self, websocket: WebSocket) -> None:
        try:
            while True:
                data = await websocket.receive_json()
                if data.get("type") == "pong":
                    self._last_pong[websocket] = time.time()
                if data.get("type") == "subscribe":
                    topics = data.get("topics", [])
                    if isinstance(topics, list):
                        self._topics[websocket] = set(topics)
                    if "live" in data:
                        self._live[websocket] = bool(data.get("live"))
        except WebSocketDisconnect:
            return
        except Exception:
            logger.warning("WebSocket message handler aborted", exc_info=True)
            return

    def _is_subscribed(self, websocket: WebSocket, topic: str) -> bool:
        topics = self._topics.get(websocket)
        if topics is None:
            return True
        return topic in topics

    def has_subscribers_for(self, topic: str) -> bool:
        for websocket in self._connections:
            if self._is_subscribed(websocket, topic):
                return True
        return False

    def has_live_subscribers_for(self, topic: str) -> bool:
        for websocket in self._connections:
            if not self._live.get(websocket, True):
                continue
            if self._is_subscribed(websocket, topic):
                return True
        return False


def _topic_for_message(message: dict) -> Optional[str]:
    msg_type = message.get("type")
    if msg_type == "state_update":
        return "state"
    if msg_type == "event":
        return "events"
    if msg_type == "progress":
        return "progress"
    if msg_type == "error":
        return "errors"
    return None
