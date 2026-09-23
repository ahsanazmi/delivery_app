from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.review import ReviewTarget


class ReviewCreate(BaseModel):
    target_type: ReviewTarget
    target_id: str = Field(min_length=1, max_length=64)
    restaurant_id: UUID | None = None
    rider_id: UUID | None = None
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class ReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    restaurant_id: UUID | None
    rider_id: UUID | None
    target_type: ReviewTarget
    target_id: str
    rating: int
    comment: str | None
    created_at: datetime
    updated_at: datetime


class OrderReviewCreate(BaseModel):
    restaurant_rating: int = Field(ge=1, le=5)
    delivery_rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class OrderReviewUpdate(BaseModel):
    restaurant_rating: int | None = Field(default=None, ge=1, le=5)
    delivery_rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class OrderReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    user_id: UUID
    restaurant_rating: int
    delivery_rating: int
    comment: str | None
    created_at: datetime
    updated_at: datetime
