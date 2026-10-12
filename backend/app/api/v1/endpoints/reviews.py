from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.deps import DbSession, require_customer
from app.models.review import ReviewTarget
from app.models.user import User
from app.schemas.review import ReviewRead
from app.services.reviews import average_rating_for_target, list_reviews_for_target

router = APIRouter()

# API Contract Validation (Phase 18) — confirmed unused by every frontend
# app today (customer-mobile creates reviews via
# /api/v1/customer/orders/{id}/review instead); hardened for consistency
# with every other write path regardless, rather than left on the bare
# CurrentUser (any authenticated role) dependency this file was missed
# with during the earlier role-isolation pass (Phase 2), which only
# covered app/api/v1/customer/*.py.


@router.post("", status_code=status.HTTP_410_GONE, deprecated=True)
def create_review_endpoint(current_user: User = Depends(require_customer)) -> None:
    """E2E Validation Phase 23 (finding A1) — closed. This generic endpoint
    took a client-supplied target and inserted a PUBLISHED review with no
    order, no delivery and no uniqueness check: any customer could post
    unlimited fake reviews for any restaurant or rider (reproduced: 5/5
    accepted for a restaurant that didn't exist). Reviews are only created
    through POST /api/v1/customer/orders/{order_id}/review, which proves the
    customer's own delivered order and allows one review per order. The
    route stays registered (and role-gated) so the legacy API contract is
    still visible; it now always answers 410 Gone. The read endpoints below
    are unchanged (frozen, see docs/reviews-ratings-architecture.md §2)."""
    _ = current_user
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Reviews are created for a delivered order: POST /api/v1/customer/orders/{order_id}/review.",
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
def average_review_score(target_type: ReviewTarget, target_id: str, db: DbSession) -> dict[str, float | str]:
    # E2E Validation Phase 4 — typed as the enum (was `str` + ReviewTarget(...)
    # in the body), so an unknown target_type is a 422 from FastAPI's own
    # validation instead of an unhandled ValueError surfacing as a 500.
    return {"target_type": target_type.value, "target_id": target_id, "average_rating": average_rating_for_target(db, target_type=target_type, target_id=target_id)}
