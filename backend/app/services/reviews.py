from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.order import OrderStatus
from app.models.review import Review, ReviewTarget
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
    return list(
        db.scalars(
            select(Review)
            .where(Review.target_type == target_type, Review.target_id == target_id)
            .order_by(Review.created_at.desc())
        )
    )


def average_rating_for_target(db: Session, *, target_type: ReviewTarget, target_id: str) -> float:
    reviews = list_reviews_for_target(db, target_type=target_type, target_id=target_id)
    if not reviews:
        return 0.0
    return round(sum(item.rating for item in reviews) / len(reviews), 2)


def create_order_review(
    db: Session,
    user_id: UUID,
    order_id: UUID,
    *,
    restaurant_rating: int,
    delivery_rating: int,
    comment: str | None,
) -> Review:
    order = get_user_order(db, user_id, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only delivered orders can be reviewed")

    existing = db.query(Review).filter(Review.order_id == order_id).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This order has already been reviewed")

    restaurant_id: UUID | None = None
    if order.restaurant_id:
        try:
            restaurant_id = UUID(order.restaurant_id)
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
        comment=comment,
    )
    db.add(review)
    db.commit()
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
        review.comment = comment

    db.commit()
    db.refresh(review)
    return review
