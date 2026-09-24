from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.coupon import DiscountType
from app.models.delivery_partner import ApprovalStatus, VehicleType
from app.models.order import OrderStatus
from app.models.rider_document import DocumentVerificationStatus
from app.models.user import UserRole
from app.schemas.order import OrderItemRead, OrderStatusHistoryRead
from app.schemas.rider_document import RiderDocumentRead
from app.schemas.rider_history import RiderHistoryItemRead


# Admin Portal Phase 23 — shared by every account-level activation/
# suspension action (customer, restaurant owner, rider, restaurant).
# Deliberately just a reason: the target state is fixed by which endpoint
# is called, never a field in the body, so there is no way to pass an
# unexpected value through — see admin_account_status.set_user_active_status.
class AdminAccountActionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AdminRiderVerificationUpdate(BaseModel):
    approval_status: ApprovalStatus
    rejection_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_reason_when_rejecting(self):
        if self.approval_status == ApprovalStatus.REJECTED and not (self.rejection_reason or "").strip():
            raise ValueError("rejection_reason is required when setting status to REJECTED")
        return self


class AdminRiderDocumentReview(BaseModel):
    verification_status: DocumentVerificationStatus
    rejection_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_reason_when_rejecting(self):
        if self.verification_status == DocumentVerificationStatus.REJECTED and not (self.rejection_reason or "").strip():
            raise ValueError("rejection_reason is required when setting status to REJECTED")
        return self


class AdminDashboardSummary(BaseModel):
    total_customers: int
    total_restaurants: int
    active_restaurants: int
    total_riders: int
    active_riders: int
    todays_orders: int
    todays_revenue: Decimal
    pending_orders: int
    pending_rider_approvals: int
    # Restaurant.approval_status == PENDING (Phase 4). Realistically 0 today
    # since restaurants default to APPROVED at creation — see
    # admin_dashboard.py's own comment on this field.
    pending_restaurant_approvals: int
    pending_cod_settlement: Decimal


class AdminRecentOrder(BaseModel):
    id: UUID
    order_number: str
    restaurant_name: str | None
    customer_name: str
    status: OrderStatus
    total: Decimal
    created_at: datetime


class AdminRecentRegistration(BaseModel):
    id: UUID
    name: str
    role: UserRole
    created_at: datetime


class AdminPendingApproval(BaseModel):
    id: UUID
    name: str
    email: str | None
    # "rider" is the only value this ever produces today — see
    # pending_restaurant_approvals above.
    type: Literal["rider"]
    submitted_at: datetime


class AdminOperationalAlert(BaseModel):
    severity: Literal["info", "warning", "critical"]
    message: str
    count: int
    # Admin Portal Phase 24 — a relative admin-web path (e.g.
    # "/riders?approval_status=PENDING"), always present since every
    # alert here must be clickable straight to its relevant section.
    link: str


class AdminDashboardResponse(BaseModel):
    summary: AdminDashboardSummary
    recent_orders: list[AdminRecentOrder]
    recent_registrations: list[AdminRecentRegistration]
    pending_approvals: list[AdminPendingApproval]
    alerts: list[AdminOperationalAlert]


# "ACTIVE"/"SUSPENDED" rather than exposing the raw is_active boolean
# directly — a clearer vocabulary for an admin table/filter, and the same
# words the status-filter query param and the PATCH payload below use.
AdminCustomerStatus = Literal["ACTIVE", "SUSPENDED"]


class AdminCustomerSummary(BaseModel):
    id: UUID
    name: str
    email: str | None
    phone: str | None
    status: AdminCustomerStatus
    created_at: datetime
    order_count: int
    # Sum of DELIVERED orders only — what the customer has actually paid
    # for, not gross order value including cancelled/rejected attempts.
    total_spending: Decimal


class AdminCustomerListResponse(BaseModel):
    items: list[AdminCustomerSummary]
    total: int
    page: int
    limit: int


class AdminCustomerDetail(AdminCustomerSummary):
    recent_orders: list[AdminRecentOrder]


# Distinct from ApprovalStatus (PENDING/APPROVED/REJECTED/SUSPENDED, the
# restaurant's standing with the platform, changed via "Suspend"/approve).
# "ACTIVE"/"INACTIVE" here is the separate owner/admin on-off switch
# (Restaurant.is_active), changed via "Activate/deactivate".
AdminRestaurantStatus = Literal["ACTIVE", "INACTIVE"]


class AdminMenuItem(BaseModel):
    id: UUID
    name: str
    price: Decimal
    is_active: bool


class AdminRestaurantSummary(BaseModel):
    id: UUID
    name: str
    phone: str
    email: str | None
    owner_id: UUID
    owner_name: str
    status: AdminRestaurantStatus
    approval_status: ApprovalStatus
    # Only ever non-null while approval_status == REJECTED — see Phase 6's
    # reject action and Restaurant.rejection_reason's own comment.
    rejection_reason: str | None
    is_open: bool
    average_rating: Decimal
    created_at: datetime
    order_count: int
    # Sum of DELIVERED orders' totals for this restaurant — the same
    # "earnings"/"revenue" figure, shown under either name depending on
    # context (list table calls it revenue, the phase's own backend
    # wording calls the same figure "earnings").
    total_revenue: Decimal


class AdminRestaurantListResponse(BaseModel):
    items: list[AdminRestaurantSummary]
    total: int
    page: int
    limit: int


class AdminRestaurantDetail(AdminRestaurantSummary):
    owner_email: str | None
    owner_phone: str | None
    menu: list[AdminMenuItem]
    recent_orders: list[AdminRecentOrder]
    # Maps & Location System Phase 3 — "Admin should be able to inspect
    # the location" was previously unmet: neither this schema nor
    # AdminRestaurantSummary carried address/coordinates at all.
    address: str
    latitude: Decimal
    longitude: Decimal
    formatted_address: str | None
    place_id: str | None


class AdminRestaurantRejectRequest(BaseModel):
    rejection_reason: str = Field(min_length=1, max_length=1000)


# Just the owner's own on/off switch (User.is_active) — "Activation" and
# "Suspension" from the phase brief are the same toggle, worded as two
# actions, the same way Phase 3 treats a customer's ACTIVE/SUSPENDED.
AdminRestaurantOwnerStatus = Literal["ACTIVE", "SUSPENDED"]


class AdminOwnedRestaurant(BaseModel):
    id: UUID
    name: str
    is_active: bool
    approval_status: ApprovalStatus


class AdminRestaurantOwnerSummary(BaseModel):
    id: UUID
    name: str
    email: str | None
    phone: str | None
    status: AdminRestaurantOwnerStatus
    created_at: datetime
    # An owner can have zero (a fresh account that hasn't set one up yet),
    # one, or more than one restaurant — never a single owner_id-shaped
    # field, since that would misrepresent the real one-to-many relationship.
    restaurants: list[AdminOwnedRestaurant]


class AdminRestaurantOwnerListResponse(BaseModel):
    items: list[AdminRestaurantOwnerSummary]
    total: int
    page: int
    limit: int


class AdminRiderSummary(BaseModel):
    id: UUID
    name: str
    phone: str | None
    email: str | None
    approval_status: ApprovalStatus
    rejection_reason: str | None
    is_online: bool
    vehicle_type: VehicleType | None
    vehicle_number: str | None
    # Average of Review.delivery_rating across every order this rider
    # delivered — 0.0 for a rider with no rated deliveries yet, never a
    # fabricated number (see admin_riders.py for the exact query).
    rating: float
    deliveries_count: int
    # Lifetime sum of RiderEarning.amount — the same ledger
    # GET /rider/earnings/summary reads from, just totalled platform-wide
    # for this one rider rather than paginated.
    total_earnings: Decimal
    created_at: datetime
    # Admin Portal Phase 23 — the account-level on/off switch (User.is_active),
    # distinct from approval_status (delivery eligibility, Phase 7/9). A
    # deactivated rider can't log in at all; a suspended-but-active one can
    # still open the app, just can't go online or accept deliveries.
    is_active: bool


class AdminRiderListResponse(BaseModel):
    items: list[AdminRiderSummary]
    total: int
    page: int
    limit: int


class AdminRiderDetail(AdminRiderSummary):
    documents: list[RiderDocumentRead]
    recent_deliveries: list[RiderHistoryItemRead]


class AdminRiderApprovalAction(BaseModel):
    # One PATCH, one action per call — mirrors the phase's own four words
    # (Activate/Suspend/Approve/Reject) as the one field that decides which
    # transition is attempted; see admin_riders.py's transition table for
    # exactly which current approval_status each action is valid from.
    action: Literal["approve", "reject", "suspend", "activate"]
    # Admin Intervention Validation (Phase 21) — required for every action,
    # not just reject: every administrative intervention must record why,
    # same as order cancel / COD settle / restaurant approval. Doubles as
    # DeliveryPartner.rejection_reason when action == "reject" — one reason,
    # not two redundant fields.
    reason: str = Field(min_length=1, max_length=1000)


class AdminRiderDocumentRejectRequest(BaseModel):
    rejection_reason: str = Field(min_length=1, max_length=1000)


class AdminRiderRejectRequest(BaseModel):
    rejection_reason: str = Field(min_length=1, max_length=1000)


class AdminOrderSummary(BaseModel):
    id: UUID
    order_number: str
    customer_name: str
    restaurant_name: str | None
    # None whenever the order has no rider assigned yet (or never needed
    # one) — not every order reaches RIDER_ASSIGNED.
    rider_name: str | None
    status: OrderStatus
    payment_method: str
    payment_status: str
    subtotal: Decimal
    delivery_fee: Decimal
    tax: Decimal
    discount: Decimal
    total: Decimal
    created_at: datetime


class AdminOrderListResponse(BaseModel):
    items: list[AdminOrderSummary]
    total: int
    page: int
    limit: int


class AdminOrderDetail(AdminOrderSummary):
    customer_email: str
    customer_phone: str | None
    restaurant_phone: str | None
    restaurant_address: str | None
    # Chronological, oldest first — the actual order timeline.
    items: list[OrderItemRead]
    status_history: list[OrderStatusHistoryRead]


class AdminOrderCancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class AdminOrderReassignRiderRequest(BaseModel):
    new_rider_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


# Order State Rule audit — assign-rider (first assignment to an unclaimed
# order) is exclusively an admin action (see services.orders.
# assign_rider_to_order's only caller), so it must carry the same
# "explicit and audited" shape as cancel/reassign-rider above, not the
# bare query-param call it started as in Phase 10.
class AdminOrderAssignRiderRequest(BaseModel):
    rider_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


# The phase brief lists PENDING as a viewable state, but DeliveryAssignment
# itself never persists a PENDING row (see that model's own docstring) — an
# unclaimed READY_FOR_PICKUP order with no rider IS the "pending" state.
# Synthesized rows for those are merged into the same list (id=None, no
# rider) so admin visibility genuinely covers the whole pipeline, not just
# orders someone has already acted on. ARRIVED_AT_RESTAURANT is a real
# status the phase's own list omits but the data can actually have, kept
# here rather than silently hidden.
AdminAssignmentStatusValue = Literal[
    "PENDING", "ACCEPTED", "REJECTED", "ARRIVED_AT_RESTAURANT", "PICKED_UP", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"
]


class AdminDeliveryAssignmentSummary(BaseModel):
    # None only for a synthesized PENDING entry — there is no real
    # DeliveryAssignment row to point to yet.
    id: UUID | None
    order_id: UUID
    order_number: str
    rider_id: UUID | None
    rider_name: str | None
    status: AdminAssignmentStatusValue
    accepted_at: datetime | None
    picked_up_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime


class AdminDeliveryAssignmentListResponse(BaseModel):
    items: list[AdminDeliveryAssignmentSummary]
    total: int
    page: int
    limit: int


class AdminDeliveryAssignmentDetail(AdminDeliveryAssignmentSummary):
    restaurant_name: str | None
    customer_name: str | None
    rejected_at: datetime | None
    rejection_reason: str | None
    arrived_at: datetime | None
    out_for_delivery_at: datetime | None
    cancelled_at: datetime | None
    updated_at: datetime


# The phase brief lists CANCELLED as a payment status, but PaymentStatus
# has no such value and no code path ever sets one — a payment for a
# cancelled order is simply left PENDING forever (nothing ever collects
# it). Rather than silently omitting the filter or fabricating a new enum
# value, CANCELLED is synthesized for exactly that combination (payment
# still PENDING, its order CANCELLED) — see admin_payments.py. REFUND_PENDING
# is real but the phase's own list omits it; kept visible rather than hidden.
# PARTIALLY_REFUNDED and PROCESSING (Phase 23) — every remaining real
# PaymentStatus value, so _derived_status()'s plain .value.upper() can
# never hand this Literal a value it doesn't recognize.
AdminPaymentStatusValue = Literal[
    "PENDING", "PROCESSING", "PAID", "FAILED", "REFUND_PENDING", "PARTIALLY_REFUNDED", "REFUNDED", "CANCELLED"
]
AdminPaymentMethodValue = Literal["razorpay", "cod"]


class AdminPaymentSummary(BaseModel):
    id: UUID
    order_id: UUID
    order_number: str
    customer_name: str
    amount: Decimal
    method: AdminPaymentMethodValue
    # Admin Payment Management (Phase 27) — distinct from `method` above:
    # `method` is the customer's own choice (cod vs online), `provider` is
    # which external gateway actually processed it — "Razorpay" for an
    # online payment, None for COD (cash has no external provider at
    # all). The two happen to be a 1:1 mapping today (Razorpay is the only
    # online provider this codebase integrates), but they answer genuinely
    # different questions, so a second online provider later wouldn't
    # collapse them back into one field.
    provider: str | None
    status: AdminPaymentStatusValue
    # razorpay_payment_id if the payment actually went through, else
    # whatever razorpay_order_id was issued — never the signature, and
    # never any provider secret/API key (see this phase's own "never
    # expose secret payment-provider credentials").
    transaction_reference: str | None
    # Admin Payment Management (Phase 27) — the most recent real Refund
    # row's own status (pending/processing/completed/failed), or None if
    # this payment has never had a refund attempted. Deliberately not the
    # legacy Payment.refund_status column (a single free-text field no
    # code path has ever actually written to, always null in practice,
    # predating the real, append-only Refund model from Phase 2/23) —
    # this is computed fresh from the real refund history every time, the
    # same principle refund_service.py's own recompute_payment_refund_status
    # already applies to the parent Payment's own status.
    latest_refund_status: str | None
    created_at: datetime
    # Admin Payment Management (Phase 27) — when the payment was actually
    # confirmed paid (Payment.paid_at), distinct from created_at (set the
    # moment the row is first opened, long before an online payment has
    # actually succeeded). None until a payment genuinely succeeds.
    paid_at: datetime | None


class AdminPaymentListResponse(BaseModel):
    items: list[AdminPaymentSummary]
    total: int
    page: int
    limit: int


class AdminRefundRecord(BaseModel):
    id: UUID
    amount: Decimal
    status: str
    provider_refund_id: str | None
    reason: str | None
    created_at: datetime


class AdminPaymentDetail(AdminPaymentSummary):
    customer_email: str
    currency: str
    is_verified: bool
    failure_reason: str | None
    collected_by_rider_name: str | None
    collected_at: datetime | None
    updated_at: datetime
    # Refund Architecture (Phase 23) — everything an admin needs to see
    # before deciding a refund amount: the real, append-only history
    # (never just the single legacy refund_status string above, which
    # can't represent more than one refund) and the two derived figures
    # that history implies — refunded_amount is never taken from a client,
    # always summed fresh from these same rows.
    refunded_amount: Decimal
    refundable_amount: Decimal
    refunds: list[AdminRefundRecord]


class AdminRefundCreateRequest(BaseModel):
    # Reason is mandatory here — unlike AdminCODSettleRequest's own
    # optional note, this phase explicitly requires it ("Admin must
    # provide: Refund amount, Reason").
    amount: Decimal = Field(gt=0)
    reason: str = Field(min_length=1, max_length=1000)


# COD Reconciliation (Phase 14). "Expected settlement" and "COD collected"
# are deliberately the same number under two labels — one is "what actually
# happened" (collection), the other frames it as "what we expect back from
# this rider" (the settlement target) — a standard reconciliation-report
# pairing. "Outstanding" is what's left after settled amounts are applied;
# never netted against the rider's own earnings (see rider_wallet.py's own
# design note — COD debt and earnings are always two separate ledgers).
AdminCODSettlementStatus = Literal["PENDING", "PARTIAL", "SETTLED"]


class AdminCODReconciliationSummary(BaseModel):
    rider_id: UUID
    rider_name: str
    cod_collected: Decimal
    expected_settlement: Decimal
    settled_amount: Decimal
    outstanding_amount: Decimal
    status: AdminCODSettlementStatus


class AdminCODReconciliationListResponse(BaseModel):
    items: list[AdminCODReconciliationSummary]
    total: int
    page: int
    limit: int


class AdminCODSettlementAllocationRecord(BaseModel):
    """Financial Ledger Validation (Phase 30) — exactly which collected
    order this portion of a settlement discharges, so a settlement is
    never just a lump-sum figure with no way to trace it back to the
    actual cash it accounts for."""

    cod_collection_id: UUID
    order_id: UUID
    order_number: str
    amount_allocated: Decimal
    collected_at: datetime


class AdminCODSettlementRecord(BaseModel):
    id: UUID
    amount: Decimal
    note: str | None
    created_at: datetime
    allocations: list[AdminCODSettlementAllocationRecord]


class AdminCODReconciliationDetail(AdminCODReconciliationSummary):
    # REMITTANCE-only — PAYOUT settlements (the platform paying the rider
    # their own earnings) are a separate concern from COD debt and are
    # deliberately excluded from this reconciliation-focused history.
    settlements: list[AdminCODSettlementRecord]


class AdminCODSettleRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=1000)


# Phase 15 — the platform-wide, home-page-browsing Category model
# (app/models/category.py). Deliberately distinct from MenuCategory
# (restaurant-scoped menu sections, managed by the restaurant owner via
# app/api/v1/restaurant/categories.py) — this admin module never touches
# that model at all. See admin_categories.py for the ownership boundary.
class AdminCategoryRead(BaseModel):
    id: UUID
    name: str
    image_url: str | None
    display_order: int
    is_active: bool
    # How many restaurants currently reference this category — surfaced so
    # an admin can see the blast radius before trying to delete one.
    restaurant_count: int
    created_at: datetime
    updated_at: datetime


class AdminCategoryListResponse(BaseModel):
    items: list[AdminCategoryRead]
    total: int
    page: int
    limit: int


class AdminCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    image_url: str | None = Field(default=None, max_length=2048)
    display_order: int = 0


class AdminCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    image_url: str | None = Field(default=None, max_length=2048)
    display_order: int | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self):
        if self.name is None and self.image_url is None and self.display_order is None and self.is_active is None:
            raise ValueError("Provide at least one field to update")
        return self


# Phase 16 — platform delivery/service-area management. Postal codes live
# in a separate table server-side (ServiceAreaPostalCode) so "is this
# pincode deliverable" is a single indexed lookup, but the admin-facing API
# just takes/returns a flat list — the child-row bookkeeping is entirely
# internal to admin_service_areas.py.
class AdminServiceAreaRead(BaseModel):
    id: UUID
    city: str
    district: str | None
    zone_name: str
    postal_codes: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AdminServiceAreaListResponse(BaseModel):
    items: list[AdminServiceAreaRead]
    total: int
    page: int
    limit: int


class AdminServiceAreaCreate(BaseModel):
    city: str = Field(min_length=1, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    zone_name: str = Field(min_length=1, max_length=120)
    postal_codes: list[str] = Field(min_length=1)
    is_active: bool = True


class AdminServiceAreaUpdate(BaseModel):
    city: str | None = Field(default=None, min_length=1, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    zone_name: str | None = Field(default=None, min_length=1, max_length=120)
    # Replaces the entire postal-code set for this zone when provided —
    # not a merge/append, so the admin always sees exactly what they sent.
    postal_codes: list[str] | None = Field(default=None, min_length=1)
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self):
        if all(
            value is None
            for value in (self.city, self.district, self.zone_name, self.postal_codes, self.is_active)
        ):
            raise ValueError("Provide at least one field to update")
        return self


# Phase 17 — commission rules. restaurant_id absent/None in a read means
# "the platform-wide default"; present means a restaurant-specific
# override. Changing a rule here never touches Order.commission_amount on
# any order already placed — see CommissionRule's own docstring and
# create_order()'s snapshot-at-creation-time behavior.
AdminCommissionType = Literal["PERCENTAGE", "FIXED"]


class AdminCommissionRuleRead(BaseModel):
    restaurant_id: UUID | None
    restaurant_name: str | None
    commission_type: AdminCommissionType
    value: Decimal
    updated_at: datetime


class AdminCommissionConfigRead(BaseModel):
    # None only when no platform default has ever been configured — a
    # real, honest "not set" rather than a fabricated 0%.
    default: AdminCommissionRuleRead | None
    restaurant_overrides: list[AdminCommissionRuleRead]


class AdminCommissionDefaultInput(BaseModel):
    commission_type: AdminCommissionType
    value: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def percentage_within_range(self):
        if self.commission_type == "PERCENTAGE" and self.value > 100:
            raise ValueError("A percentage commission cannot exceed 100")
        return self


class AdminCommissionOverrideInput(BaseModel):
    restaurant_id: UUID
    commission_type: AdminCommissionType
    value: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def percentage_within_range(self):
        if self.commission_type == "PERCENTAGE" and self.value > 100:
            raise ValueError("A percentage commission cannot exceed 100")
        return self


class AdminCommissionUpdateRequest(BaseModel):
    # Three explicit, non-overlapping actions — "rules must be explicit"
    # means no single field doing double duty (e.g. null-to-remove).
    default: AdminCommissionDefaultInput | None = None
    upsert_restaurant_overrides: list[AdminCommissionOverrideInput] | None = None
    remove_restaurant_override_ids: list[UUID] | None = None

    @model_validator(mode="after")
    def require_at_least_one_change(self):
        if self.default is None and not self.upsert_restaurant_overrides and not self.remove_restaurant_override_ids:
            raise ValueError(
                "Provide at least one change: default, upsert_restaurant_overrides, or remove_restaurant_override_ids"
            )
        return self


# Phase 18 — the proper, complete admin coupon surface at /admin/coupons.
# A separate, pre-existing admin coupon router already lives at the bare
# /api/v1/coupons path (app/api/v1/endpoints/coupons.py) with its own
# security-regression test history — left untouched rather than merged or
# removed, since this phase doesn't ask for that and doing so would risk a
# test protecting a real, previously-fixed vulnerability for no benefit.
def _validate_percent_range(discount_type: DiscountType | None, discount_value: Decimal | None) -> None:
    if discount_type == DiscountType.PERCENT and discount_value is not None and discount_value > 100:
        raise ValueError("A percentage discount cannot exceed 100")


class AdminCouponRead(BaseModel):
    id: UUID
    code: str
    discount_type: DiscountType
    discount_value: Decimal
    min_order: Decimal
    max_discount: Decimal | None
    start_date: datetime | None
    end_date: datetime | None
    usage_limit: int | None
    per_customer_limit: int | None
    restaurant_id: UUID | None
    restaurant_name: str | None
    is_active: bool
    # How many times this coupon has actually been redeemed — real usage,
    # not the configured cap.
    redemption_count: int
    created_at: datetime
    updated_at: datetime


class AdminCouponListResponse(BaseModel):
    items: list[AdminCouponRead]
    total: int
    page: int
    limit: int


class AdminCouponCreate(BaseModel):
    code: str = Field(min_length=3, max_length=64)
    discount_type: DiscountType
    discount_value: Decimal = Field(gt=0)
    min_order: Decimal = Field(default=Decimal("0.00"), ge=0)
    max_discount: Decimal | None = Field(default=None, ge=0)
    start_date: datetime | None = None
    end_date: datetime | None = None
    usage_limit: int | None = Field(default=None, ge=1)
    per_customer_limit: int | None = Field(default=1, ge=1)
    restaurant_id: UUID | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_rules(self):
        _validate_percent_range(self.discount_type, self.discount_value)
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class AdminCouponUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=3, max_length=64)
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, gt=0)
    min_order: Decimal | None = Field(default=None, ge=0)
    max_discount: Decimal | None = Field(default=None, ge=0)
    start_date: datetime | None = None
    end_date: datetime | None = None
    usage_limit: int | None = Field(default=None, ge=1)
    per_customer_limit: int | None = Field(default=None, ge=1)
    restaurant_id: UUID | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self):
        if all(
            value is None
            for value in (
                self.code, self.discount_type, self.discount_value, self.min_order, self.max_discount,
                self.start_date, self.end_date, self.usage_limit, self.per_customer_limit, self.restaurant_id,
                self.is_active,
            )
        ):
            raise ValueError("Provide at least one field to update")
        return self

    @model_validator(mode="after")
    def validate_rules(self):
        _validate_percent_range(self.discount_type, self.discount_value)
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


# Phase 21 — Audit Logs. Field names here (entity_type/entity_id/old_value/
# new_value) are the phase's own vocabulary; the underlying AdminAuditLog
# table (Phase 11) uses target_type/target_id/previous_state/new_state —
# the same data, renamed only at this read-only API boundary rather than
# migrating three existing writers' column names.
class AdminAuditLogSummary(BaseModel):
    id: UUID
    admin_id: UUID
    admin_name: str | None
    action: str
    entity_type: str
    entity_id: str
    reason: str
    ip_address: str | None
    created_at: datetime


class AdminAuditLogDetail(AdminAuditLogSummary):
    old_value: str | None
    new_value: str | None


class AdminAuditLogListResponse(BaseModel):
    items: list[AdminAuditLogSummary]
    total: int
    page: int
    limit: int


# Phase 22 — Admin Settings. A single platform-wide row; see
# app.models.platform_settings.PlatformSettings for why "default commission"
# is deliberately absent (it already lives in CommissionRule, Phase 17).
class AdminPlatformSettingsRead(BaseModel):
    id: UUID
    platform_name: str
    support_email: str | None
    support_phone: str | None
    default_delivery_fee: Decimal
    default_minimum_order: Decimal
    notifications_enabled: bool
    maintenance_mode: bool
    updated_at: datetime


class AdminPlatformSettingsUpdate(BaseModel):
    platform_name: str | None = Field(default=None, min_length=1, max_length=160)
    support_email: str | None = Field(default=None, max_length=255)
    support_phone: str | None = Field(default=None, max_length=20)
    default_delivery_fee: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    default_minimum_order: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    notifications_enabled: bool | None = None
    maintenance_mode: bool | None = None
    # Not persisted — recorded on the audit log entry this update writes.
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_at_least_one_field(self):
        if all(
            value is None
            for value in (
                self.platform_name, self.support_email, self.support_phone, self.default_delivery_fee,
                self.default_minimum_order, self.notifications_enabled, self.maintenance_mode,
            )
        ):
            raise ValueError("Provide at least one field to update")
        return self
