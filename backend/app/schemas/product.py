from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class MenuCategoryRead(BaseModel):
    """Customer-facing projection — no is_active (the list is already
    filtered to active-only) or timestamps, which customers have no use for."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    restaurant_id: UUID
    name: str
    display_order: int


class MenuCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    display_order: int = Field(default=0, ge=0)
    image_url: HttpUrl | None = None


class MenuCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    display_order: int | None = Field(default=None, ge=0)
    image_url: HttpUrl | None = None
    is_active: bool | None = None


class OwnerMenuCategoryRead(BaseModel):
    """Owner-facing projection — includes is_active (for the enable/disable
    toggle) and image_url, which customers never see directly."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    restaurant_id: UUID
    name: str
    image_url: str | None
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    restaurant_id: UUID
    category_id: UUID | None
    name: str
    description: str | None
    image_url: str | None
    price: Decimal
    is_available: bool


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    category_id: UUID | None = None
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    image_url: HttpUrl | None = None
    is_available: bool = True


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    category_id: UUID | None = None
    price: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    image_url: HttpUrl | None = None
    is_available: bool | None = None


class OwnerProductRead(BaseModel):
    """Owner-facing projection — same shape as ProductRead today, but kept
    separate since the owner surface (unlike customer discovery) will show
    products regardless of is_available/category state, and may grow
    owner-only fields later without touching the customer contract."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    restaurant_id: UUID
    category_id: UUID | None
    name: str
    description: str | None
    image_url: str | None
    price: Decimal
    is_available: bool
    created_at: datetime
    updated_at: datetime
