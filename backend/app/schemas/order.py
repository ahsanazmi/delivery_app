from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.order import OrderStatus


class CustomerOrderCreate(BaseModel):
    address_id: UUID
    # Checkout Payment Decision (Phase 6) — a real customer choice between
    # the two supported methods. Never anything beyond this literal pair:
    # which *provider* handles "razorpay" is entirely PaymentService's own
    # decision, never the client's. Availability (is Razorpay actually
    # configured right now) is checked server-side in create_order(), not
    # here — this schema only constrains the shape, not the business rule.
    payment_method: Literal["cod", "razorpay"] = "cod"
    delivery_instructions: str | None = Field(default=None, max_length=500)


class OrderRejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


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


class RestaurantOrderListItem(BaseModel):
    """The owner's incoming-orders list — a quick-glance summary with the
    customer's name masked (full name/phone/address are only in the detail
    view, via OrderRead, which the owner reaches by opening a specific order
    to actually fulfill it)."""

    id: UUID
    order_number: str
    customer_name_masked: str
    item_count: int
    total: Decimal
    payment_method: str
    # Restaurant Payment Visibility (Phase 28) — Order.payment_status
    # (not Payment's own, richer enum — never joins in the Payment model
    # here at all, so there is no path by which a razorpay_signature or
    # any other payment-security field could ever end up on this
    # restaurant-owner-facing response).
    payment_status: str
    status: OrderStatus
    created_at: datetime
    # Restaurant Payment Visibility (Phase 28) — see
    # app/services/orders.py::compute_restaurant_financials()'s own note
    # on why these are never recomputed from a possibly-changed
    # CommissionRule. Restaurant-owner-only fields — deliberately never
    # added to the shared OrderRead below, which customer/rider/admin
    # endpoints also return and which has no reason to expose the
    # platform's commission structure to anyone but the restaurant it
    # was charged to (and admins, who already see it via
    # AdminPaymentDetail's own separate schema).
    restaurant_earning: Decimal
    commission: Decimal
    net_amount: Decimal


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    rider_id: UUID | None
    customer_name: str
    customer_email: str
    customer_phone: str | None
    restaurant_id: str | None
    restaurant_name: str | None
    restaurant_phone: str | None
    restaurant_address: str | None
    order_number: str
    status: OrderStatus
    payment_method: str
    subtotal: Decimal
    delivery_fee: Decimal
    tax: Decimal
    discount: Decimal
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
    payment_status: str
    is_paid: bool
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead]
    status_history: list[OrderStatusHistoryRead]


class RestaurantOrderDetailRead(OrderRead):
    """Restaurant Payment Visibility (Phase 28) — the restaurant owner's
    own order-detail response. Deliberately a separate schema from the
    shared OrderRead above (which customer/rider/admin endpoints also
    return as-is) rather than adding these fields to OrderRead directly —
    a customer or rider has no reason to see the platform's commission
    structure for an order. See RestaurantOrderListItem's own note and
    app/services/orders.py::compute_restaurant_financials() for why these
    figures never move once computed."""

    restaurant_earning: Decimal
    commission: Decimal
    net_amount: Decimal
