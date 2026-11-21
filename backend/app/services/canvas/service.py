"""Real-time collaborative canvas via WebSocket broadcast."""

import logging
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class CanvasSession:
    id: str
    session_id: str
    elements: list[dict] = field(default_factory=list)
    subscribers: list[WebSocket] = field(default_factory=list)


class CanvasManager:
    def __init__(self) -> None:
        self._canvases: dict[str, CanvasSession] = {}

    def get_or_create(self, session_id: str) -> CanvasSession:
        for canvas in self._canvases.values():
            if canvas.session_id == session_id:
                return canvas
        canvas = CanvasSession(id=str(uuid.uuid4()), session_id=session_id)
        self._canvases[canvas.id] = canvas
        return canvas

    async def connect(self, canvas_id: str, ws: WebSocket) -> None:
        canvas = self._canvases.get(canvas_id)
        if not canvas:
            await ws.close(code=4004)
            return
        await ws.accept()
        canvas.subscribers.append(ws)
        await ws.send_json({"type": "state", "elements": canvas.elements})

    async def disconnect(self, canvas_id: str, ws: WebSocket) -> None:
        canvas = self._canvases.get(canvas_id)
        if canvas and ws in canvas.subscribers:
            canvas.subscribers.remove(ws)

    async def handle_message(self, canvas_id: str, ws: WebSocket, data: dict) -> None:
        canvas = self._canvases.get(canvas_id)
        if not canvas:
            return

        msg_type = data.get("type")
        if msg_type == "draw":
            canvas.elements.append(data.get("element", {}))
        elif msg_type == "clear":
            canvas.elements.clear()
        elif msg_type == "undo" and canvas.elements:
            canvas.elements.pop()

        for subscriber in list(canvas.subscribers):
            if subscriber is ws:
                continue
            try:
                await subscriber.send_json(data)
            except Exception:
                canvas.subscribers.remove(subscriber)

    def get_canvas_for_session(self, session_id: str) -> CanvasSession | None:
        for canvas in self._canvases.values():
            if canvas.session_id == session_id:
                return canvas
        return None

    def get_canvas(self, canvas_id: str) -> CanvasSession | None:
        return self._canvases.get(canvas_id)


canvas_manager = CanvasManager()

__all__ = ["CanvasManager", "CanvasSession", "canvas_manager"]
