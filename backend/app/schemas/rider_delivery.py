from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.delivery_assignment import AssignmentStatus
from app.models.order import OrderStatus
from app.models.payment import PaymentStatus
from app.schemas.order import OrderItemRead


class DeliveryRejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class DeliveryAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    rider_id: UUID
    status: AssignmentStatus
    accepted_at: datetime | None
    rejected_at: datetime | None
    rejection_reason: str | None
    arrived_at: datetime | None
    picked_up_at: datetime | None
    out_for_delivery_at: datetime | None
    delivered_at: datetime | None
    cancelled_at: datetime | None


class AvailableDeliveryRead(BaseModel):
    # A DeliveryAssignment row only exists once a rider has actually accepted
    # or rejected an order (see app/models/delivery_assignment.py) — while an
    # order is still unclaimed and just being shown as available, there's no
    # row for it yet, so assignment_id and order_id are the same value here.
    assignment_id: UUID
    order_id: UUID

    restaurant_name: str
    restaurant_address: str
    restaurant_latitude: Decimal | None
    restaurant_longitude: Decimal | None

    # Deliberately coarse — city only. No customer name, phone, exact
    # address, landmark, or coordinates before the rider actually has this
    # assignment; that's exactly the personal information a rider doesn't
    # need to decide whether to take the delivery.
    customer_area: str

    estimated_distance_km: float | None
    # Same simple proxy as the dashboard's today_earnings — the order's
    # delivery_fee, not a real earnings-ledger figure (no incentives/bonuses
    # yet; that's the dedicated Earnings phase's job).
    estimated_earning: Decimal

    ready_since: datetime


class RiderDeliveryDetailRead(BaseModel):
    """The full picture — only reachable once this rider is actually
    assigned (get_rider_delivery_or_404 scopes every lookup to
    Order.rider_id == this rider), unlike the available-deliveries list,
    which deliberately shows only the coarse city. A rider fulfilling a
    delivery genuinely needs the customer's name, phone, and exact address —
    that's the entire justification for waiting until assignment to reveal it."""

    order_id: UUID
    order_number: str
    status: OrderStatus
    # The rider's own step within RIDER_ASSIGNED (Phase 13) — null if no
    # DeliveryAssignment row exists yet (e.g. an order assigned directly by
    # an admin, never through accept_delivery()). Lets the frontend render
    # "Arrived" vs "Pick up" correctly even after a reload, since Order.status
    # itself never changes for the arrival step.
    assignment_status: AssignmentStatus | None

    restaurant_name: str
    restaurant_phone: str | None
    restaurant_address: str
    restaurant_latitude: Decimal | None
    restaurant_longitude: Decimal | None

    customer_name: str
    customer_phone: str | None
    delivery_address_line: str
    delivery_city: str
    delivery_state: str | None
    delivery_postal_code: str
    delivery_landmark: str | None
    delivery_latitude: Decimal | None
    delivery_longitude: Decimal | None
    delivery_instructions: str | None

    items: list[OrderItemRead]
    subtotal: Decimal
    delivery_fee: Decimal
    total: Decimal
    payment_method: str
    is_paid: bool
    # Only meaningful for an unpaid COD order — the amount the rider must
    # actually collect from the customer. None for a prepaid/already-settled
    # order, so the frontend doesn't show a collection prompt that doesn't apply.
    cod_amount: Decimal | None

    created_at: datetime


class CodCollectionRead(BaseModel):
    """Response for POST /deliveries/{id}/cod-collect. Every value here is
    derived server-side from the order/payment record — the request body
    accepts nothing, so there is no field a rider could submit to influence
    the amount, status, or timestamp recorded."""

    model_config = ConfigDict(from_attributes=True)

    order_id: UUID
    payment_id: UUID
    amount: Decimal
    payment_status: PaymentStatus
    collected_by_rider_id: UUID
    collected_at: datetime
