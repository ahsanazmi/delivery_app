from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CartItemCreate(BaseModel):
    product_id: UUID
    quantity: int = Field(default=1, ge=1, le=100)


class CartItemUpdate(BaseModel):
    quantity: int = Field(ge=1, le=100)


class CartItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    product_name: str
    unit_price: Decimal
    quantity: int
    created_at: datetime
    updated_at: datetime


class CartRestaurantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    logo_url: str | None
    minimum_order: Decimal
    delivery_fee: Decimal
    is_open: bool


class CartRead(BaseModel):
    restaurant: CartRestaurantRead | None
    items: list[CartItemRead]
    subtotal: Decimal
    delivery_fee: Decimal
    tax: Decimal
    discount: Decimal
    total: Decimal
    total_items: int
    removed_items: list[str] = Field(default_factory=list)
    coupon_code: str | None = None
    coupon_message: str | None = None
