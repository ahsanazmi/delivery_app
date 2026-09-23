from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.services.orders import get_user_order
from app.services.tracking_snapshot import build_tracking_snapshot


def get_order_tracking(db: Session, user_id: UUID, order_id: UUID) -> dict:
    order = get_user_order(db, user_id, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return build_tracking_snapshot(db, order)
