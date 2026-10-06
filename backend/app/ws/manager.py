import asyncio
from collections import defaultdict
from uuid import UUID

from fastapi import WebSocket


class OrderTrackingConnectionManager:
    """In-process fan-out from one order's room to every socket watching it.

    This lives in a single worker's memory — fine for this app's current
    single-uvicorn-process deployment, but it means a broadcast only reaches
    sockets connected to *this* process. Scaling to multiple workers/instances
    would need a shared pub/sub (e.g. Redis) behind the same broadcast()
    interface; nothing above this class would need to change.
    """

    def __init__(self) -> None:
        self._connections: dict[UUID, set[WebSocket]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None
        # asyncio only holds a *weak* reference to a scheduled task/future — with
        # nothing else keeping it alive, a broadcast's future can be garbage
        # collected mid-flight before it actually sends anything. Holding a
        # strong reference here until each one completes is what makes
        # broadcast() reliable rather than a race.
        self._pending: set[asyncio.Future] = set()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, order_id: UUID, websocket: WebSocket) -> None:
        self._connections[order_id].add(websocket)

    def disconnect(self, order_id: UUID, websocket: WebSocket) -> None:
        connections = self._connections.get(order_id)
        if not connections:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop(order_id, None)

    async def _send_to_all(self, order_id: UUID, payload: dict) -> None:
        for websocket in list(self._connections.get(order_id, ())):
            try:
                await websocket.send_json(payload)
            except Exception:
                self.disconnect(order_id, websocket)

    def has_listeners(self, order_id: UUID) -> bool:
        """Live Rider Tracking Phase 35 — Performance/Scalability. A cheap
        O(1) check callers can use to skip building an expensive snapshot
        (a DB read plus a possible live-ETA/OSRM call) when nobody is
        actually connected to watch it — see rider_location.py's own use
        of this, on the high-frequency GPS-driven broadcast path."""
        return order_id in self._connections

    def broadcast(self, order_id: UUID, payload: dict) -> None:
        """Safe to call from synchronous service-layer code running off the
        event loop thread (FastAPI runs sync `def` routes in a threadpool)."""
        if self._loop is None or order_id not in self._connections:
            return
        future = asyncio.run_coroutine_threadsafe(self._send_to_all(order_id, payload), self._loop)
        self._pending.add(future)
        future.add_done_callback(self._pending.discard)

    async def _close_all(self, order_id: UUID) -> None:
        for websocket in list(self._connections.get(order_id, ())):
            try:
                await websocket.close(code=1000)
            except Exception:
                pass
        self._connections.pop(order_id, None)

    def close_room(self, order_id: UUID) -> None:
        """Live Rider Tracking Phase 28/31 — proactively closes every
        connection currently subscribed to this order, rather than
        leaving that entirely to a well-behaved client eventually closing
        its own socket after receiving a terminal status. This class has
        no opinion on *why* a room should close (no order/business logic
        here, per Phase 13's own separation) — the caller decides when."""
        if self._loop is None or order_id not in self._connections:
            return
        future = asyncio.run_coroutine_threadsafe(self._close_all(order_id), self._loop)
        self._pending.add(future)
        future.add_done_callback(self._pending.discard)


manager = OrderTrackingConnectionManager()
