from datetime import date, datetime, time
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.delivery_assignment import AssignmentStatus, DeliveryAssignment
from app.models.order import Order, OrderStatus
from app.models.user import User
from app.schemas.admin import (
    AdminAssignmentStatusValue,
    AdminDeliveryAssignmentDetail,
    AdminDeliveryAssignmentListResponse,
    AdminDeliveryAssignmentSummary,
)

# Realistic scale for this project — an in-Python merge of two already
# filtered, indexed queries is simple and fast here. A platform with tens
# of thousands of assignments would want a real SQL UNION (or a
# materialized view) instead of this; not needed yet.


def _to_summary_from_assignment(assignment: DeliveryAssignment, order: Order, rider: User | None) -> AdminDeliveryAssignmentSummary:
    return AdminDeliveryAssignmentSummary(
        id=assignment.id,
        order_id=assignment.order_id,
        order_number=order.order_number,
        rider_id=assignment.rider_id,
        rider_name=rider.name if rider else None,
        status=assignment.status.value,
        accepted_at=assignment.accepted_at,
        picked_up_at=assignment.picked_up_at,
        delivered_at=assignment.delivered_at,
        created_at=assignment.created_at,
    )


def _to_summary_from_pending_order(order: Order) -> AdminDeliveryAssignmentSummary:
    return AdminDeliveryAssignmentSummary(
        id=None,
        order_id=order.id,
        order_number=order.order_number,
        rider_id=None,
        rider_name=None,
        status="PENDING",
        accepted_at=None,
        picked_up_at=None,
        delivered_at=None,
        created_at=order.created_at,
    )


def _real_assignments(
    db: Session, *, search: str | None, status_filter: AdminAssignmentStatusValue | None,
    date_from: date | None, date_to: date | None,
) -> list[tuple[datetime, AdminDeliveryAssignmentSummary]]:
    if status_filter == "PENDING":
        return []  # no real assignment row is ever PENDING

    conditions = []
    if status_filter is not None:
        conditions.append(DeliveryAssignment.status == AssignmentStatus(status_filter))
    if date_from is not None:
        conditions.append(DeliveryAssignment.created_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        conditions.append(DeliveryAssignment.created_at <= datetime.combine(date_to, time.max))

    query = (
        select(DeliveryAssignment, Order, User)
        .join(Order, Order.id == DeliveryAssignment.order_id)
        .outerjoin(User, User.id == DeliveryAssignment.rider_id)
        .where(*conditions)
    )
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(Order.order_number.ilike(pattern) | User.name.ilike(pattern))

    rows = db.execute(query).all()
    return [(assignment.created_at, _to_summary_from_assignment(assignment, order, rider)) for assignment, order, rider in rows]


def _pending_entries(
    db: Session, *, search: str | None, status_filter: AdminAssignmentStatusValue | None,
    date_from: date | None, date_to: date | None,
) -> list[tuple[datetime, AdminDeliveryAssignmentSummary]]:
    if status_filter is not None and status_filter != "PENDING":
        return []

    conditions = [Order.status == OrderStatus.READY_FOR_PICKUP, Order.rider_id.is_(None)]
    if search:
        conditions.append(Order.order_number.ilike(f"%{search.strip()}%"))
    if date_from is not None:
        conditions.append(Order.created_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        conditions.append(Order.created_at <= datetime.combine(date_to, time.max))

    orders = db.scalars(select(Order).where(*conditions)).all()
    return [(order.created_at, _to_summary_from_pending_order(order)) for order in orders]


def list_admin_delivery_assignments(
    db: Session,
    *,
    search: str | None,
    status_filter: AdminAssignmentStatusValue | None,
    date_from: date | None,
    date_to: date | None,
    page: int,
    limit: int,
) -> AdminDeliveryAssignmentListResponse:
    entries = _real_assignments(db, search=search, status_filter=status_filter, date_from=date_from, date_to=date_to)
    entries += _pending_entries(db, search=search, status_filter=status_filter, date_from=date_from, date_to=date_to)
    entries.sort(key=lambda pair: pair[0], reverse=True)

    total = len(entries)
    offset = (page - 1) * limit
    items = [summary for _, summary in entries[offset : offset + limit]]
    return AdminDeliveryAssignmentListResponse(items=items, total=total, page=page, limit=limit)


def get_admin_delivery_assignment_detail(db: Session, assignment_id: UUID) -> AdminDeliveryAssignmentDetail:
    assignment = db.get(DeliveryAssignment, assignment_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery assignment not found")
    order = db.get(Order, assignment.order_id)
    rider = db.get(User, assignment.rider_id)

    return AdminDeliveryAssignmentDetail(
        id=assignment.id,
        order_id=assignment.order_id,
        order_number=order.order_number if order else "",
        rider_id=assignment.rider_id,
        rider_name=rider.name if rider else None,
        status=assignment.status.value,
        accepted_at=assignment.accepted_at,
        picked_up_at=assignment.picked_up_at,
        delivered_at=assignment.delivered_at,
        created_at=assignment.created_at,
        restaurant_name=order.restaurant_name if order else None,
        customer_name=order.customer_name if order else None,
        rejected_at=assignment.rejected_at,
        rejection_reason=assignment.rejection_reason,
        arrived_at=assignment.arrived_at,
        out_for_delivery_at=assignment.out_for_delivery_at,
        cancelled_at=assignment.cancelled_at,
        updated_at=assignment.updated_at,
    )
