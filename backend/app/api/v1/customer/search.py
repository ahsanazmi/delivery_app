from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.customer.location_params import CustomerLocation, customer_location
from app.api.v1.deps import DbSession
from app.schemas.search import SearchResponse
from app.services.search import run_customer_search

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
def search(
    db: DbSession,
    q: str | None = Query(default=None, alias="q"),
    category_id: UUID | None = Query(default=None),
    restaurant_id: UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    location: CustomerLocation | None = Depends(customer_location),
) -> SearchResponse:
    result = run_customer_search(
        db, q=q, category_id=category_id, restaurant_id=restaurant_id, page=page, limit=limit,
        latitude=location.latitude if location else None,
        longitude=location.longitude if location else None,
    )
    return SearchResponse(**result)
