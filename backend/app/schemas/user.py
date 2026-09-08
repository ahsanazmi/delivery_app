from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.user import UserRole


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: EmailStr | None
    phone: str | None
    role: UserRole
    profile_image: str | None
    is_active: bool
    created_at: datetime


class UserRoleUpdate(BaseModel):
    role: UserRole
