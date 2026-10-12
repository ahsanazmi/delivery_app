import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from app.models.user import UserRole

# E2E Validation Phase 8 — shared input types for a person's identity fields.
# Names are stripped *before* the length check (a bare `min_length=2` then a
# later .strip() let "   " through and saved an empty name). Phones must look
# like a phone: digits with optional spaces/dashes/parentheses and an
# optional leading "+", 8–15 digits — previously any 8–20 characters
# ("abcdefgh") was accepted. The stored value is unchanged (still the
# stripped input), so existing phone-based logins keep matching exactly.
_PHONE_CHARACTERS = re.compile(r"^\+?[0-9(][0-9 ()-]*$")


def _check_phone(value: str) -> str:
    digits = sum(ch.isdigit() for ch in value)
    if not _PHONE_CHARACTERS.match(value) or not 8 <= digits <= 15:
        raise ValueError("Enter a valid phone number (digits, optionally starting with +).")
    return value


PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
PhoneNumber = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=20), AfterValidator(_check_phone)]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    # Plain str on output: stored emails were validated on input, and
    # re-running EmailStr here 500s /auth/me for any already-stored address
    # it rejects (e.g. reserved TLDs like ".test").
    email: str | None
    phone: str | None
    role: UserRole
    profile_image: str | None
    is_active: bool
    created_at: datetime


class UserRoleUpdate(BaseModel):
    role: UserRole
