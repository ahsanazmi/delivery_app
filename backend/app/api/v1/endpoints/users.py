from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.deps import CurrentUser, DbSession, require_roles
from app.models.user import User, UserRole
from app.schemas.user import UserRead, UserRoleUpdate

router = APIRouter()


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: CurrentUser) -> UserRead:
    return current_user


@router.patch("/{user_id}/role", response_model=UserRead)
def update_user_role(
    user_id: UUID,
    payload: UserRoleUpdate,
    db: DbSession,
    current_admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> UserRead:
    """Assign operational roles. Public registration can only create customers."""
    if current_admin.id == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Administrators cannot change their own role")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.role = payload.role
    db.commit()
    db.refresh(user)
    return user
