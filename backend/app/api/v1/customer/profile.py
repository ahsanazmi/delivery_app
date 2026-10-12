from fastapi import APIRouter, Depends, HTTPException, status
from app.api.v1.deps import DbSession, require_customer
from app.models.user import User
from app.schemas.user import PersonName, UserRead
from app.services.auth import get_user_by_email
from pydantic import BaseModel, EmailStr, constr
from sqlalchemy.exc import IntegrityError

router = APIRouter()


class ProfileUpdate(BaseModel):
    name: PersonName | None = None
    email: EmailStr | None = None
    profile_image: constr(max_length=2048) | None = None


@router.get("/profile", response_model=UserRead)
def read_profile(current_user: User = Depends(require_customer)) -> UserRead:
    return current_user


@router.patch("/profile", response_model=UserRead)
def update_profile(payload: ProfileUpdate, db: DbSession, current_user: User = Depends(require_customer)) -> UserRead:
    # update allowed fields only on current_user
    if payload.name is not None:
        current_user.name = payload.name.strip()
    if payload.email is not None:
        # E2E Validation Phase 7 — previously no uniqueness check: changing to
        # another account's email hit the users.email unique constraint as an
        # unhandled IntegrityError (500), and the 500-vs-200 difference told
        # the caller whether that email is registered. Same clean 409 as
        # rider_service.update_rider_profile.
        normalized_email = payload.email.lower().strip()
        existing = get_user_by_email(db, normalized_email)
        if existing and existing.id != current_user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")
        current_user.email = normalized_email
    if payload.profile_image is not None:
        current_user.profile_image = payload.profile_image
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request claimed the same email between the check above and this commit.
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists") from None
    db.refresh(current_user)
    return current_user
