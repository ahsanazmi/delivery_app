from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.address import AddressRead
from app.schemas.cart import CartItemRead, CartRestaurantRead


class CheckoutResponse(BaseModel):
    addresses: list[AddressRead]
    selected_address: AddressRead | None
    restaurant: CartRestaurantRead | None
    items: list[CartItemRead]
    subtotal: Decimal
    delivery_fee: Decimal
    tax: Decimal
    discount: Decimal
    total: Decimal
    total_items: int
    removed_items: list[str]
    coupon_code: str | None
    coupon_message: str | None
    issues: list[str]


class OrderValidateRequest(BaseModel):
    address_id: UUID


class OrderValidateResponse(BaseModel):
    valid: bool
    issues: list[str]
    address: AddressRead | None
    restaurant: CartRestaurantRead | None
    items: list[CartItemRead]
    subtotal: Decimal
    delivery_fee: Decimal
    tax: Decimal
    discount: Decimal
    total: Decimal
    total_items: int
    removed_items: list[str]
    coupon_code: str | None
