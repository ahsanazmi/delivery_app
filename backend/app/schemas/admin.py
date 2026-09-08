from pydantic import BaseModel

from app.models.order import OrderStatus


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    note: str | None = None


class AdminDashboard(BaseModel):
    total_orders: int
    pending_orders: int
    total_customers: int
    active_restaurants: int
