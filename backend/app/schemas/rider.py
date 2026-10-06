from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.delivery_partner import ApprovalStatus, VehicleType


class RiderVerificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    approval_status: ApprovalStatus
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class RiderStatusRead(BaseModel):
    approval_status: ApprovalStatus
    is_online: bool
    # Computed, not stored — lets the frontend grey out / explain the "Go
    # online" toggle proactively instead of only finding out after a failed
    # PATCH. The backend re-checks all of this independently on the PATCH
    # itself regardless of what this said a moment ago.
    can_go_online: bool
    online_blocked_reason: str | None
    updated_at: datetime


class RiderStatusUpdate(BaseModel):
    is_online: bool


class RiderVehicleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vehicle_type: VehicleType | None
    vehicle_number: str | None
    vehicle_model: str | None
    updated_at: datetime


class RiderVehicleUpdate(BaseModel):
    vehicle_type: VehicleType | None = None
    vehicle_number: str | None = Field(default=None, min_length=1, max_length=20)
    vehicle_model: str | None = Field(default=None, min_length=1, max_length=120)


class RiderProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, min_length=8, max_length=20)
    email: EmailStr | None = None
    profile_image: str | None = Field(default=None, max_length=2048)


class RiderLocationUpdate(BaseModel):
    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)
    # All optional — a device that can't report them (or an older client
    # build) can still send a bare lat/lng.
    accuracy: Decimal | None = Field(default=None, ge=0, description="Reported horizontal accuracy, in meters")
    heading: Decimal | None = Field(default=None, ge=0, lt=360, description="Degrees clockwise from true north")
    speed: Decimal | None = Field(default=None, ge=0, description="Ground speed, in meters/second")
    # Live Rider Tracking Phase 3/6 — both new, both optional for the same
    # backward-compatibility reason as the three above.
    altitude: Decimal | None = Field(default=None, description="Meters above sea level")
    # The device's own claimed capture time — never trusted alone (see
    # services/rider_location.py's timestamp plausibility check); the
    # server's own receipt time remains authoritative for throttling and
    # ordering regardless of what this says.
    captured_at: datetime | None = Field(default=None)


class RiderLocationRead(BaseModel):
    # Nullable: a rider who has never reported a position at all has
    # nothing to echo back yet. An ineligible caller (not ONLINE and no
    # active delivery) no longer reaches this response at all — Live
    # Rider Tracking Phase 6 — it's rejected outright (403) instead.
    latitude: Decimal | None
    longitude: Decimal | None
    accuracy: Decimal | None
    heading: Decimal | None
    speed: Decimal | None
    updated_at: datetime | None
