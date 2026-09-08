from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CartItemCreate(BaseModel):
    product_id: str = Field(min_length=1, max_length=64)
    restaurant_id: str = Field(min_length=1, max_length=64)
    product_name: str = Field(min_length=1, max_length=160)
    unit_price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    quantity: int = Field(default=1, ge=1, le=100)


class CartItemUpdate(BaseModel):
    quantity: int = Field(ge=1, le=100)


class CartItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: str
    restaurant_id: str
    product_name: str
    unit_price: Decimal
    quantity: int
    created_at: datetime
    updated_at: datetime


class CartRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    restaurant_id: str | None
    items: list[CartItemRead]
    subtotal: Decimal
    total_items: int
    total: Decimal
    created_at: datetime
    updated_at: datetime
