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
    # Maps & Location System Phase 19 — Checkout Location Integration:
    # "Distance where appropriate." Straight-line, server-computed
    # (LocationService.distance_km) — None whenever either the selected
    # address or the restaurant has no pinned coordinates, since both are
    # optional elsewhere in this platform and this is purely informational
    # (delivery fee is a flat, owner-configured amount, not distance-based
    # — see Phase 18), never required to check out.
    distance_km: float | None
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
    distance_km: float | None
