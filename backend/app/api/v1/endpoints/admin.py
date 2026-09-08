from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.v1.deps import CurrentUser, DbSession
from app.models.order import Order, OrderStatus, OrderStatusHistory
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.schemas.admin import AdminDashboard, OrderStatusUpdate
from app.schemas.order import OrderRead
from app.schemas.restaurant import RestaurantRead
from app.schemas.user import UserRead
from app.services.orders import assign_rider_to_order

router = APIRouter()


def _require_admin(current_user: CurrentUser) -> CurrentUser:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


@router.get("/dashboard", response_model=AdminDashboard)
def get_dashboard(db: DbSession, current_user: CurrentUser) -> AdminDashboard:
    _require_admin(current_user)
    total_orders = db.scalar(select(func.count()).select_from(Order)) or 0
    pending_orders = (
        db.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.status.notin_([OrderStatus.DELIVERED, OrderStatus.CANCELLED]))
        )
        or 0
    )
    total_customers = db.scalar(select(func.count()).select_from(User).where(User.role == UserRole.CUSTOMER)) or 0
    active_restaurants = db.scalar(select(func.count()).select_from(Restaurant).where(Restaurant.is_active.is_(True))) or 0
    return AdminDashboard(
        total_orders=total_orders,
        pending_orders=pending_orders,
        total_customers=total_customers,
        active_restaurants=active_restaurants,
    )


@router.get("/customers", response_model=list[UserRead])
def list_customers(db: DbSession, current_user: CurrentUser) -> list[UserRead]:
    _require_admin(current_user)
    customers = db.scalars(select(User).where(User.role == UserRole.CUSTOMER).order_by(User.created_at.desc())).all()
    return list(customers)


@router.get("/restaurants", response_model=list[RestaurantRead])
def list_restaurants(db: DbSession, current_user: CurrentUser) -> list[RestaurantRead]:
    _require_admin(current_user)
    restaurants = db.scalars(select(Restaurant).order_by(Restaurant.created_at.desc())).all()
    return list(restaurants)


@router.get("/orders", response_model=list[OrderRead])
def list_all_orders(db: DbSession, current_user: CurrentUser) -> list[OrderRead]:
    _require_admin(current_user)
    return db.scalars(select(Order).order_by(Order.created_at.desc())).all()


@router.get("/riders", response_model=list[UserRead])
def list_riders(db: DbSession, current_user: CurrentUser) -> list[UserRead]:
    _require_admin(current_user)
    riders = db.scalars(select(User).where(User.role == UserRole.RIDER).order_by(User.created_at.desc())).all()
    return list(riders)


@router.patch("/orders/{order_id}/assign-rider", response_model=OrderRead)
def assign_rider(
    order_id: UUID,
    rider_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> OrderRead:
    _require_admin(current_user)
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    try:
        return assign_rider_to_order(db, order, rider_id)
    except HTTPException:
        raise


@router.patch("/orders/{order_id}/status", response_model=OrderRead)
def update_order_status(
    order_id: UUID,
    payload: OrderStatusUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> OrderRead:
    _require_admin(current_user)
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    previous_status = order.status
    order.status = payload.status
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            status=payload.status,
            note=payload.note or f"Status updated from {previous_status.value} to {payload.status.value}",
        )
    )
    db.commit()
    db.refresh(order)
    return order
