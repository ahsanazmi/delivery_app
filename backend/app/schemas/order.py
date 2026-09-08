from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.order import OrderStatus


class OrderItemCreate(BaseModel):
    product_id: str
    restaurant_id: str
    product_name: str
    unit_price: Decimal
    quantity: int = Field(default=1, ge=1)


class OrderCreate(BaseModel):
    restaurant_name: str | None = None
    restaurant_phone: str | None = None
    address_line: str = Field(min_length=3, max_length=500)
    city: str = Field(min_length=2, max_length=120)
    state: str | None = Field(default=None, min_length=2, max_length=120)
    postal_code: str = Field(min_length=3, max_length=20)
    landmark: str | None = Field(default=None, max_length=200)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=10, decimal_places=7)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=10, decimal_places=7)
    delivery_instructions: str | None = Field(default=None, max_length=500)
    payment_method: str = Field(default="cod", max_length=32)


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    product_id: str
    restaurant_id: str
    product_name: str
    unit_price: Decimal
    quantity: int
    created_at: datetime


class OrderStatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    status: OrderStatus
    note: str | None
    created_at: datetime


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    rider_id: UUID | None
    restaurant_id: str | None
    restaurant_name: str | None
    restaurant_phone: str | None
    order_number: str
    status: OrderStatus
    payment_method: str
    subtotal: Decimal
    delivery_fee: Decimal
    total: Decimal
    item_count: int
    address_line: str
    city: str
    state: str | None
    postal_code: str
    landmark: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    delivery_instructions: str | None
    cancelled_reason: str | None
    is_paid: bool
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead]
    status_history: list[OrderStatusHistoryRead]
