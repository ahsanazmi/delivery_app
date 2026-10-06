from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AddressCreate(BaseModel):
    label: str = Field(default="Home", min_length=1, max_length=50)
    recipient_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=20)
    address_line: str = Field(min_length=3, max_length=500)
    city: str = Field(min_length=2, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    state: str = Field(min_length=2, max_length=120)
    postal_code: str = Field(min_length=3, max_length=20)
    landmark: str | None = Field(default=None, max_length=200)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=10, decimal_places=7)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=10, decimal_places=7)
    formatted_address: str | None = Field(default=None, max_length=1000)
    place_id: str | None = Field(default=None, max_length=255)
    is_default: bool = False

    # Maps & Location System Phase 13 — Delivery Location Validation.
    # Coordinates are optional (manual address entry with no map pin must
    # keep working, per Phase 2), but a lone latitude with no longitude
    # (or vice versa) is never a valid state — it can only come from a
    # partial/corrupted write, not a real pinned location. This is a
    # whole-record create, so it's safe to enforce both-or-neither here;
    # AddressUpdate deliberately does NOT get this same validator since a
    # PATCH may legitimately touch just one field of an address that
    # already has the other one set from before.
    @model_validator(mode="after")
    def _both_or_neither_coordinate(self) -> "AddressCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Both latitude and longitude must be provided together, or neither.")
        return self


class AddressUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=50)
    recipient_name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, min_length=8, max_length=20)
    address_line: str | None = Field(default=None, min_length=3, max_length=500)
    city: str | None = Field(default=None, min_length=2, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, min_length=2, max_length=120)
    postal_code: str | None = Field(default=None, min_length=3, max_length=20)
    landmark: str | None = Field(default=None, max_length=200)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=10, decimal_places=7)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=10, decimal_places=7)
    formatted_address: str | None = Field(default=None, max_length=1000)
    place_id: str | None = Field(default=None, max_length=255)
    is_default: bool | None = None


class AddressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    label: str
    recipient_name: str
    phone: str
    address_line: str
    city: str
    district: str | None
    state: str
    postal_code: str
    landmark: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    formatted_address: str | None
    place_id: str | None
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
