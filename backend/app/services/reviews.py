from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatus
from app.models.review import Review, ReviewStatus, ReviewTarget
from app.services.orders import get_user_order


def create_review(db: Session, *, user_id: UUID, target_type: ReviewTarget, target_id: str, rating: int, comment: str | None, restaurant_id: UUID | None = None, rider_id: UUID | None = None) -> Review:
    review = Review(
        user_id=user_id,
        target_type=target_type,
        target_id=target_id,
        rating=rating,
        comment=comment,
        restaurant_id=restaurant_id,
        rider_id=rider_id,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def list_reviews_for_target(db: Session, *, target_type: ReviewTarget, target_id: str) -> list[Review]:
    # Public, unauthenticated read path (app/api/v1/endpoints/reviews.py) — a
    # HIDDEN/FLAGGED/REMOVED review must never surface here as if it were an
    # ordinary PUBLISHED one.
    return list(
        db.scalars(
            select(Review)
            .where(
                Review.target_type == target_type,
                Review.target_id == target_id,
                Review.status == ReviewStatus.PUBLISHED,
            )
            .order_by(Review.created_at.desc())
        )
    )


def average_rating_for_target(db: Session, *, target_type: ReviewTarget, target_id: str) -> float:
    reviews = list_reviews_for_target(db, target_type=target_type, target_id=target_id)
    if not reviews:
        return 0.0
    return round(sum(item.rating for item in reviews) / len(reviews), 2)


def _normalize_comment(comment: str | None) -> str | None:
    """Reviews & Ratings Phase 13 — a comment that is only whitespace is
    treated as no comment at all, rather than stored as an empty-looking
    string. Deliberately does nothing else: no language/script filtering
    (legitimate multilingual text, including non-Latin scripts and emoji,
    passes through byte-for-byte), and no profanity/abuse blocklist at
    write time — per the master command's own instruction, abuse is
    handled after the fact via reporting and moderation, not a write-time
    filter that risks rejecting legitimate feedback."""
    if comment is None:
        return None
    stripped = comment.strip()
    return stripped or None


def check_review_eligibility(db: Session, user_id: UUID, order_id: UUID) -> Order:
    """Reviews & Ratings Phase 7 — the eligibility gate every review-submission
    path must pass before touching the Review table:

        authenticated user -> customer -> owns order -> order delivered -> eligible review target

    The first two steps ("authenticated user", "customer") are enforced one
    layer up, by the route's own `require_customer` dependency — this
    codebase's established convention (docs/reviews-ratings-architecture.md
    §6) is role authorization at the route layer, not re-checked in every
    service function. This function owns the rest of the chain, and is the
    one place that chain is implemented — callers must not re-derive any of
    it themselves, and the client is never trusted to have determined any
    of it (Rule 3).

    Deliberately does *not* check "already reviewed" (Phase 8's rule) — that
    is a separate concern from *can this order be reviewed at all*, kept in
    its own check at each call site so eligibility and duplicate-prevention
    can be tested and reasoned about independently.
    """
    order = get_user_order(db, user_id, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only delivered orders can be reviewed")
    if not order.restaurant_id:
        # Order.restaurant_id is nullable at the model level; a DELIVERED
        # order should never actually lack one, but this is the one place
        # eligibility is decided, so it is the one place that gets verified
        # rather than assumed.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This order has no reviewable restaurant")
    if not order.rider_id:
        # Reviews & Ratings Phase 11 — "rider was assigned to order" and
        # "rider delivery completed" are both implied by status == DELIVERED
        # for the normal flow (a rider must be assigned and must complete
        # delivery to reach that state — see rider_deliveries.py), but
        # Order.rider_id has ondelete="SET NULL": if a rider account is ever
        # deleted after delivering, a past order's rider_id silently becomes
        # NULL. Without this check, delivery_rating would be stored against
        # no rider at all — not "an unrelated rider" (that's already
        # impossible, since rider_id is never client-supplied — Phase 9),
        # but a rating orphaned from any rider, which is its own integrity
        # problem this phase's checklist is asking to close.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This order has no reviewable rider")
    return order


def create_order_review(
    db: Session,
    user_id: UUID,
    order_id: UUID,
    *,
    restaurant_rating: int,
    delivery_rating: int,
    comment: str | None,
) -> Review:
    order = check_review_eligibility(db, user_id, order_id)

    # Reviews & Ratings Phase 8 — one-review-per-order, application layer.
    # This check alone has a TOCTOU race (two concurrent requests for the
    # same order can both pass it before either commits); the
    # uq_reviews_order_id UniqueConstraint below is what actually closes
    # that gap, not this check by itself. Both layers exist because neither
    # is sufficient alone: skip this one and every duplicate attempt pays
    # for a full INSERT attempt only to be rejected by the database; skip
    # the database one and a race condition slips a duplicate through.
    existing = db.query(Review).filter(Review.order_id == order_id).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This order has already been reviewed")

    # order.restaurant_id is guaranteed truthy here (check_review_eligibility
    # above), but it's a free-form String(64), not a validated UUID column —
    # still fall back to None rather than let a malformed value 500.
    try:
        restaurant_id: UUID | None = UUID(order.restaurant_id)
    except ValueError:
        restaurant_id = None

    review = Review(
        user_id=user_id,
        order_id=order_id,
        restaurant_id=restaurant_id,
        rider_id=order.rider_id,
        target_type=ReviewTarget.RESTAURANT,
        target_id=order.restaurant_id or "",
        rating=restaurant_rating,
        restaurant_rating=restaurant_rating,
        delivery_rating=delivery_rating,
        comment=_normalize_comment(comment),
    )
    db.add(review)
    try:
        db.commit()
    except IntegrityError as exc:
        # The uq_reviews_order_id database constraint — the layer that
        # actually closes the race the check above cannot, on its own.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This order has already been reviewed"
        ) from exc
    db.refresh(review)
    return review


def get_order_review(db: Session, user_id: UUID, order_id: UUID) -> Review | None:
    order = get_user_order(db, user_id, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return db.query(Review).filter(Review.order_id == order_id).first()


def update_order_review(
    db: Session,
    user_id: UUID,
    review_id: UUID,
    *,
    restaurant_rating: int | None,
    delivery_rating: int | None,
    comment: str | None,
) -> Review:
    review = db.query(Review).filter(Review.id == review_id, Review.user_id == user_id).first()
    if not review:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

    if restaurant_rating is not None:
        review.restaurant_rating = restaurant_rating
        review.rating = restaurant_rating
    if delivery_rating is not None:
        review.delivery_rating = delivery_rating
    if comment is not None:
        review.comment = _normalize_comment(comment)

    db.commit()
    db.refresh(review)
    return review
