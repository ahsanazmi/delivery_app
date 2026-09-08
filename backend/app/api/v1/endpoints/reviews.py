from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import CurrentUser, DbSession
from app.models.review import ReviewTarget
from app.schemas.review import ReviewCreate, ReviewRead
from app.services.reviews import average_rating_for_target, create_review, list_reviews_for_target

router = APIRouter()


@router.post("", response_model=ReviewRead, status_code=status.HTTP_201_CREATED)
def create_review_endpoint(payload: ReviewCreate, db: DbSession, current_user: CurrentUser) -> ReviewRead:
    if payload.target_type == ReviewTarget.RIDER and not payload.rider_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="rider_id is required for rider reviews")
    if payload.target_type == ReviewTarget.RESTAURANT and not payload.restaurant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="restaurant_id is required for restaurant reviews")
    return create_review(
        db,
        user_id=current_user.id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        rating=payload.rating,
        comment=payload.comment,
        restaurant_id=payload.restaurant_id,
        rider_id=payload.rider_id,
    )


@router.get("/restaurant/{restaurant_id}", response_model=list[ReviewRead])
def list_restaurant_reviews(restaurant_id: UUID, db: DbSession) -> list[ReviewRead]:
    return list_reviews_for_target(db, target_type=ReviewTarget.RESTAURANT, target_id=str(restaurant_id))


@router.get("/food/{target_id}", response_model=list[ReviewRead])
def list_food_reviews(target_id: str, db: DbSession) -> list[ReviewRead]:
    return list_reviews_for_target(db, target_type=ReviewTarget.FOOD, target_id=target_id)


@router.get("/rider/{rider_id}", response_model=list[ReviewRead])
def list_rider_reviews(rider_id: UUID, db: DbSession) -> list[ReviewRead]:
    return list_reviews_for_target(db, target_type=ReviewTarget.RIDER, target_id=str(rider_id))


@router.get("/average/{target_type}/{target_id}")
def average_review_score(target_type: str, target_id: str, db: DbSession) -> dict[str, float | str]:
    review_enum = ReviewTarget(target_type)
    return {"target_type": review_enum.value, "target_id": target_id, "average_rating": average_rating_for_target(db, target_type=review_enum, target_id=target_id)}
