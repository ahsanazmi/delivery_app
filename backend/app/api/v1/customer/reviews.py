from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.v1.deps import DbSession, require_customer
from app.models.user import User
from app.schemas.review import OrderReviewCreate, OrderReviewRead, OrderReviewUpdate
from app.services.reviews import create_order_review, get_order_review, update_order_review

router = APIRouter()


@router.post("/orders/{order_id}/review", response_model=OrderReviewRead, status_code=status.HTTP_201_CREATED)
def create_review(order_id: UUID, payload: OrderReviewCreate, db: DbSession, current_user: User = Depends(require_customer)) -> OrderReviewRead:
    return create_order_review(
        db,
        current_user.id,
        order_id,
        restaurant_rating=payload.restaurant_rating,
        delivery_rating=payload.delivery_rating,
        comment=payload.comment,
    )


@router.get("/orders/{order_id}/review", response_model=OrderReviewRead | None)
def get_review(order_id: UUID, db: DbSession, current_user: User = Depends(require_customer)) -> OrderReviewRead | None:
    return get_order_review(db, current_user.id, order_id)


@router.patch("/reviews/{review_id}", response_model=OrderReviewRead)
def update_review(review_id: UUID, payload: OrderReviewUpdate, db: DbSession, current_user: User = Depends(require_customer)) -> OrderReviewRead:
    return update_order_review(
        db,
        current_user.id,
        review_id,
        restaurant_rating=payload.restaurant_rating,
        delivery_rating=payload.delivery_rating,
        comment=payload.comment,
    )
