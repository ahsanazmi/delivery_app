from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class RestaurantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    phone: str = Field(min_length=8, max_length=20)
    address: str = Field(min_length=5, max_length=2000)
    latitude: Decimal = Field(ge=-90, le=90, max_digits=10, decimal_places=7)
    longitude: Decimal = Field(ge=-180, le=180, max_digits=10, decimal_places=7)
    minimum_order: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=10, decimal_places=2)
    delivery_fee: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=10, decimal_places=2)
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


class RestaurantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    phone: str
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
