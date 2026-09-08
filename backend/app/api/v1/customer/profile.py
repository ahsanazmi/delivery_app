from fastapi import APIRouter, HTTPException, status
from app.api.v1.deps import CurrentUser, DbSession
from app.schemas.user import UserRead
from pydantic import BaseModel, EmailStr, constr
from app.models.user import UserRole

router = APIRouter()


class ProfileUpdate(BaseModel):
    name: constr(min_length=2, max_length=120) | None = None
    email: EmailStr | None = None
    profile_image: constr(max_length=2048) | None = None


@router.get("/profile", response_model=UserRead)
def read_profile(current_user: CurrentUser) -> UserRead:
    return current_user


@router.patch("/profile", response_model=UserRead)
def update_profile(payload: ProfileUpdate, db: DbSession, current_user: CurrentUser) -> UserRead:
    # Only customers may use this endpoint
    if current_user.role != UserRole.CUSTOMER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    # update allowed fields only on current_user
    if payload.name is not None:
        current_user.name = payload.name.strip()
    if payload.email is not None:
        current_user.email = payload.email.lower().strip()
    if payload.profile_image is not None:
        current_user.profile_image = payload.profile_image
    db.commit()
    db.refresh(current_user)
    return current_user
