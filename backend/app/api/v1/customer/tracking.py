import logging
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect

from app.api.v1.deps import DbSession, require_customer
from app.core.observability import log_event
from app.core.rate_limit import rate_limit
from app.core.security import decode_token
from app.models.user import User, UserRole
from app.schemas.tracking import OrderTrackingResponse
from app.services.orders import get_user_order
from app.services.tracking import get_order_tracking
from app.services.tracking_snapshot import build_tracking_snapshot, to_tracking_response
from app.ws.manager import manager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/orders/{order_id}/tracking", response_model=OrderTrackingResponse)
def get_tracking(
    order_id: UUID, request: Request, db: DbSession, current_user: User = Depends(require_customer)
) -> OrderTrackingResponse:
    # Live Rider Tracking Phase 33 — Fallback Polling. This is the exact
    # endpoint the client's REST-polling fallback hits while its WebSocket
    # is down (see customer-mobile/features/tracking/use-order-tracking.ts);
    # the client's own 15s interval is self-limiting for a well-behaved
    # app, but a broken or malicious client retrying in a tight loop must
    # not be able to hammer this freely — same per-IP sliding-window
    # pattern already used for customer/location.py and auth.py.
    #
    # Live Rider Tracking Phase 35 — Performance/Scalability. Keyed
    # explicitly by customer id rather than the default path+IP key: this
    # path embeds order_id, so the default key would create one permanent
    # rate_limit entry per order for the life of the process. Scoping to
    # the customer instead keeps it bounded by distinct customers, and a
    # customer polling several active orders at once correctly shares one
    # combined budget rather than getting one free 30/60s per order.
    rate_limit(request, max_attempts=30, window_seconds=60, key=f"tracking:{current_user.id}")
    result = get_order_tracking(db, current_user.id, order_id)
    return to_tracking_response(result)


@router.websocket("/ws/orders/{order_id}")
async def order_tracking_socket(websocket: WebSocket, order_id: UUID, db: DbSession) -> None:
    """Live push of order status + rider location for one order, scoped to the
    customer who placed it.

    Auth travels as `?token=<access token>` rather than an Authorization
    header — browsers and React Native's WebSocket client can't attach custom
    headers to a WS handshake, but every client (web, native, wscat) can set a
    query param, so this is the one auth transport that works everywhere.
    """
    # Live Rider Tracking Phase 39 — Observability. Never logged: the token
    # itself — every event below identifies the attempt by order_id (and
    # user_id, once known) only, never by credential content.
    token = websocket.query_params.get("token")
    if not token:
        log_event(logger, "subscription_rejected", order_id=order_id, reason="missing_token")
        await websocket.close(code=4401)
        return

    try:
        user_id = decode_token(token, "access")
    except (jwt.PyJWTError, ValueError):
        log_event(logger, "subscription_rejected", order_id=order_id, reason="invalid_token")
        await websocket.close(code=4401)
        return

    # The REST equivalent (get_current_user) also checks is_active — a
    # deactivated account's still-unexpired access token must not keep a live
    # tracking connection open either.
    user = db.get(User, user_id)
    if not user or not user.is_active or user.role != UserRole.CUSTOMER:
        log_event(logger, "subscription_rejected", order_id=order_id, user_id=user_id, reason="inactive_or_wrong_role")
        await websocket.close(code=4401)
        return

    order = get_user_order(db, user_id, order_id)
    if not order:
        log_event(logger, "subscription_rejected", order_id=order_id, user_id=user_id, reason="not_found_or_not_owned")
        await websocket.close(code=4404)
        return

    await websocket.accept()
    log_event(logger, "websocket_connected", order_id=order_id, user_id=user_id)
    await manager.connect(order_id, websocket)
    log_event(logger, "subscription_created", order_id=order_id, user_id=user_id)
    try:
        # A (re)connecting client always gets a full, fresh snapshot
        # immediately — it never has to wait for the next status change to
        # catch up after a dropped connection.
        snapshot = build_tracking_snapshot(db, order)
        await websocket.send_json(to_tracking_response(snapshot).model_dump(mode="json"))

        while True:
            # We don't expect meaningful client messages, but we must keep
            # awaiting one to detect a disconnect; a lightweight ping/pong
            # also lets the client verify the socket is still alive.
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(order_id, websocket)
        log_event(logger, "websocket_disconnected", order_id=order_id, user_id=user_id)
