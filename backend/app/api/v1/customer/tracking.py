from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api.v1.deps import DbSession, require_customer
from app.core.security import decode_token
from app.models.user import User, UserRole
from app.schemas.tracking import OrderTrackingResponse
from app.services.orders import get_user_order
from app.services.tracking import get_order_tracking
from app.services.tracking_snapshot import build_tracking_snapshot, to_tracking_response
from app.ws.manager import manager

router = APIRouter()


@router.get("/orders/{order_id}/tracking", response_model=OrderTrackingResponse)
def get_tracking(order_id: UUID, db: DbSession, current_user: User = Depends(require_customer)) -> OrderTrackingResponse:
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
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return

    try:
        user_id = decode_token(token, "access")
    except (jwt.PyJWTError, ValueError):
        await websocket.close(code=4401)
        return

    # The REST equivalent (get_current_user) also checks is_active — a
    # deactivated account's still-unexpired access token must not keep a live
    # tracking connection open either.
    user = db.get(User, user_id)
    if not user or not user.is_active or user.role != UserRole.CUSTOMER:
        await websocket.close(code=4401)
        return

    order = get_user_order(db, user_id, order_id)
    if not order:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    await manager.connect(order_id, websocket)
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
