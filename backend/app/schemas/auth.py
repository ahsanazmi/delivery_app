from pydantic import BaseModel, EmailStr, Field, TypeAdapter, ValidationError, model_validator

from app.models.user import UserRole
from app.schemas.user import PersonName, PhoneNumber

_EMAIL_ADAPTER = TypeAdapter(EmailStr)


class RegisterRequest(BaseModel):
    name: PersonName
    email: str
    password: str = Field(min_length=8, max_length=128)
    phone: PhoneNumber | None = None
    role: UserRole | None = UserRole.CUSTOMER

    @model_validator(mode="before")
    @classmethod
    def normalize_registration_fields(cls, values):
        if not isinstance(values, dict):
            return values

        phone = values.get("phone")
        if phone is not None:
            if isinstance(phone, str):
                normalized_phone = phone.strip()
                values["phone"] = normalized_phone or None
            else:
                normalized_phone = str(phone).strip()
                values["phone"] = normalized_phone or None

        role = values.get("role")
        if isinstance(role, str):
            normalized_role = role.strip()
            values["role"] = normalized_role.upper() if normalized_role else UserRole.CUSTOMER.value

        email = values.get("email")
        if isinstance(email, str):
            values["email"] = email.strip()

        return values

    @model_validator(mode="after")
    def validate_email(self):
        value = (self.email or "").strip()
        # E2E Validation Phase 5 — validated with the same EmailStr rules as
        # the UserRead response model. A bare "@" check let addresses like
        # "user@localhost" register, after which every endpoint returning
        # UserRead (/auth/me, /users/me, the register response itself) failed
        # response validation with a 500 — and the half-created account's
        # email could never be registered again.
        try:
            _EMAIL_ADAPTER.validate_python(value)
        except ValidationError:
            raise ValueError("Invalid email address") from None
        self.email = value.lower()
        return self


class LoginRequest(BaseModel):
    email: str | None = None
    phone: str | None = Field(default=None, min_length=8, max_length=20)
    password: str = Field(min_length=1, max_length=128)

    @model_validator(mode="before")
    @classmethod
    def normalize_identifier(cls, values):
        if not isinstance(values, dict):
            return values

        email = values.get("email")
        phone = values.get("phone")

        if email is not None and email != "":
            email = str(email).strip()
            if "@" not in email and phone in (None, ""):
                values["phone"] = email
                values["email"] = None
            else:
                values["email"] = email

        if phone is not None and phone != "":
            values["phone"] = str(phone).strip()

        return values

    @model_validator(mode="after")
    def validate_identifier(self):
        email = (self.email or "").strip()
        phone = (self.phone or "").strip()

        if not email and not phone:
            raise ValueError("Either email or phone is required")
        if email and "@" not in email:
            self.phone = email
            self.email = None
        return self


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
