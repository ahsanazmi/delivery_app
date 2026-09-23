from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.models.order import OrderStatus


class RestaurantOrderSummary(BaseModel):
    id: UUID
    order_number: str
    status: OrderStatus
    customer_name: str
    total: Decimal
    item_count: int
    created_at: datetime


class RestaurantDashboardResponse(BaseModel):
    restaurant_id: UUID
    restaurant_name: str
    is_open: bool

    today_orders_count: int
    pending_orders_count: int
    preparing_orders_count: int
    ready_orders_count: int
    completed_orders_count: int

    today_sales: Decimal
    pending_earnings: Decimal

    pending_orders: list[RestaurantOrderSummary]
    recent_orders: list[RestaurantOrderSummary]
