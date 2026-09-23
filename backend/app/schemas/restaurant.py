from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl

from app.schemas.user import UserRead

class RestaurantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    phone: str = Field(min_length=8, max_length=20)
    address: str = Field(min_length=5, max_length=2000)
    latitude: Decimal = Field(ge=-90, le=90, max_digits=10, decimal_places=7)
    longitude: Decimal = Field(ge=-180, le=180, max_digits=10, decimal_places=7)
    # None means "use the platform default" (Admin Portal Phase 22's
    # PlatformSettings.default_minimum_order / default_delivery_fee) —
    # resolved in services.restaurants.create_restaurant, never here.
    minimum_order: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    delivery_fee: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    owner_id: UUID | None = None


class RestaurantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    phone: str | None = Field(default=None, min_length=8, max_length=20)
    address: str | None = Field(default=None, min_length=5, max_length=2000)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=10, decimal_places=7)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=10, decimal_places=7)
    minimum_order: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    delivery_fee: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)


class RestaurantImagesUpdate(BaseModel):
    logo_url: HttpUrl | None = None
    cover_image_url: HttpUrl | None = None


class RestaurantOpenStatusUpdate(BaseModel):
    is_open: bool


class RestaurantProfileUpdate(BaseModel):
    """Everything an owner can edit about their own restaurant's profile in
    one call — a superset of RestaurantUpdate (which the older admin/owner
    /restaurants/{id} endpoint still uses) plus email and the two image URLs,
    so the owner-facing /restaurant/profile surface doesn't need three
    separate PATCH calls for what is, to the owner, one form."""

    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    phone: str | None = Field(default=None, min_length=8, max_length=20)
    email: EmailStr | None = None
    address: str | None = Field(default=None, min_length=5, max_length=2000)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=10, decimal_places=7)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=10, decimal_places=7)
    minimum_order: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    delivery_fee: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    logo_url: HttpUrl | None = None
    cover_image_url: HttpUrl | None = None


class RestaurantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    phone: str
    email: str | None
    address: str
    latitude: Decimal
    longitude: Decimal
    logo_url: str | None
    cover_image_url: str | None
    minimum_order: Decimal
    delivery_fee: Decimal
    average_rating: Decimal
    is_open: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CustomerRestaurantRead(BaseModel):
    """Public-facing restaurant projection for customer discovery endpoints.

    Excludes owner/internal fields (owner_id, is_active) that customers have no use for.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category_id: UUID | None
    name: str
    description: str | None
    address: str
    logo_url: str | None
    cover_image_url: str | None
    rating: Decimal = Field(validation_alias="average_rating")
    delivery_time_minutes: int
    minimum_order: Decimal
    delivery_fee: Decimal
    is_open: bool


class RestaurantOwnerMe(BaseModel):
    """The owner-dashboard identity check: who I am, and which restaurant(s)
    I actually manage — the one place the owner-to-restaurant relationship is
    made explicit to the client, rather than the client inferring it by
    filtering the public restaurant list itself."""

    user: UserRead
    restaurants: list[RestaurantRead]
