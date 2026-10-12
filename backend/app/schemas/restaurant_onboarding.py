from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints, TypeAdapter, ValidationError, field_validator

from app.schemas.user import PersonName, PhoneNumber

_EMAIL_ADAPTER = TypeAdapter(EmailStr)

RestaurantName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
RestaurantAddress = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]


class RestaurantOnboardingRequest(BaseModel):
    """A restaurant-owner account plus its first restaurant, created together
    in one transaction. Shared by the public partner application (restaurant
    lands PENDING until an admin approves it) and the admin portal's "Add
    restaurant" form (lands APPROVED) — RESTAURANT_OWNER still can't come in
    through plain /auth/register, since an owner without a restaurant has
    nothing to manage."""

    owner_name: PersonName
    email: str
    password: str = Field(min_length=8, max_length=128)
    owner_phone: PhoneNumber | None = None
    restaurant_name: RestaurantName
    description: str | None = Field(default=None, max_length=5000)
    restaurant_phone: PhoneNumber
    address: RestaurantAddress
    latitude: Decimal = Field(ge=-90, le=90, max_digits=10, decimal_places=7)
    longitude: Decimal = Field(ge=-180, le=180, max_digits=10, decimal_places=7)
    formatted_address: str | None = Field(default=None, max_length=1000)
    place_id: str | None = Field(default=None, max_length=255)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        # Same EmailStr rules RegisterRequest applies, so a stored owner email
        # is always one every other part of the system accepts.
        value = value.strip()
        try:
            _EMAIL_ADAPTER.validate_python(value)
        except ValidationError:
            raise ValueError("Invalid email address") from None
        return value.lower()

    @field_validator("owner_phone", mode="before")
    @classmethod
    def blank_phone_is_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value
