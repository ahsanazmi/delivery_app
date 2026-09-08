import secrets
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.cart import Cart
from app.models.order import Order, OrderItem, OrderStatus, OrderStatusHistory
from app.models.user import User, UserRole
from app.services.cart import clear_cart, get_cart_for_user


def _next_order_number() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    suffix = secrets.token_hex(3).upper()
    return f"ORD-{stamp}-{suffix}"


def _add_status_history(db: Session, order: Order, status: OrderStatus, note: str | None = None) -> OrderStatusHistory:
    history = OrderStatusHistory(order_id=order.id, status=status, note=note)
    db.add(history)
    db.flush()
    return history


def create_order_from_cart(db: Session, user_id: UUID, payload: dict) -> Order:
    cart = get_cart_for_user(db, user_id)
    if not cart.items:
        raise ValueError("Cart is empty")

    subtotal = sum((item.unit_price * item.quantity for item in cart.items), Decimal("0.00"))
    delivery_fee = Decimal("0.00")
    total = subtotal + delivery_fee

    order = Order(
        user_id=user_id,
        restaurant_id=cart.restaurant_id,
        restaurant_name=str(payload.get("restaurant_name") or "Restaurant"),
        restaurant_phone=str(payload.get("restaurant_phone") or ""),
        order_number=_next_order_number(),
        status=OrderStatus.PENDING,
        payment_method=str(payload.get("payment_method") or "cod"),
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        total=total,
        item_count=sum(item.quantity for item in cart.items),
        address_line=str(payload.get("address_line") or ""),
        city=str(payload.get("city") or ""),
        state=str(payload.get("state") or None),
        postal_code=str(payload.get("postal_code") or ""),
        landmark=str(payload.get("landmark") or None),
        latitude=payload.get("latitude"),
        longitude=payload.get("longitude"),
        delivery_instructions=str(payload.get("delivery_instructions") or None),
        is_paid=False,
    )
    db.add(order)
    db.flush()

    for item in cart.items:
        order_item = OrderItem(
            order_id=order.id,
            product_id=str(item.product_id),
            restaurant_id=str(item.restaurant_id),
            product_name=str(item.product_name),
            unit_price=item.unit_price,
            quantity=item.quantity,
        )
        db.add(order_item)

    _add_status_history(db, order, OrderStatus.PENDING, "Order placed")
    clear_cart(db, cart)
    db.commit()
    db.refresh(order)
    return order


def list_user_orders(db: Session, user_id: UUID) -> list[Order]:
    return list(db.query(Order).filter(Order.user_id == user_id).order_by(Order.created_at.desc()).all())


def get_user_order(db: Session, user_id: UUID, order_id: UUID) -> Order | None:
    return db.query(Order).filter(Order.user_id == user_id, Order.id == order_id).first()


def cancel_order(db: Session, user_id: UUID, order_id: UUID, reason: str | None = None) -> Order:
    order = get_user_order(db, user_id, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order.status in {OrderStatus.DELIVERED, OrderStatus.CANCELLED}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Order cannot be cancelled")
    order.status = OrderStatus.CANCELLED
    order.cancelled_reason = reason
    _add_status_history(db, order, OrderStatus.CANCELLED, reason or "Cancelled by customer")
    db.commit()
    db.refresh(order)
    return order


def assign_rider_to_order(db: Session, order: Order, rider_id: UUID) -> Order:
    rider = db.get(User, rider_id)
    if not rider or rider.role != UserRole.RIDER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected rider is invalid")
    order.rider_id = rider_id
    if order.status == OrderStatus.PENDING:
        order.status = OrderStatus.CONFIRMED
    _add_status_history(db, order, order.status, f"Assigned to rider {rider.name}")
    db.commit()
    db.refresh(order)
    return order


def list_rider_orders(db: Session, rider_id: UUID) -> list[Order]:
    return list(
        db.query(Order)
        .filter(Order.rider_id == rider_id)
        .order_by(Order.created_at.desc())
        .all()
    )


def update_rider_order_status(db: Session, rider_id: UUID, order_id: UUID, status: OrderStatus, note: str | None = None) -> Order:
    order = db.query(Order).filter(Order.id == order_id, Order.rider_id == rider_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assigned order not found")
    if status == OrderStatus.OUT_FOR_DELIVERY and order.status in {OrderStatus.PENDING, OrderStatus.CONFIRMED}:
        order.status = OrderStatus.OUT_FOR_DELIVERY
    elif status == OrderStatus.DELIVERED:
        order.status = OrderStatus.DELIVERED
    else:
        order.status = status
    _add_status_history(db, order, order.status, note or f"Marked by rider as {order.status.value}")
    db.commit()
    db.refresh(order)
    return order
