from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.review import Review, ReviewTarget


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
