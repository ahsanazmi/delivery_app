from fastapi import APIRouter, Query, status

from app.api.v1.deps import CurrentUser, DbSession
from app.schemas.push_token import PushTokenCreate, PushTokenRead
from app.services.notifications import delete_push_token, upsert_push_token

router = APIRouter()


@router.post("/register", response_model=PushTokenRead)
def register_push_token(payload: PushTokenCreate, db: DbSession, current_user: CurrentUser) -> PushTokenRead:
    return upsert_push_token(db, current_user.id, payload.token, payload.platform)


@router.delete("/register", status_code=status.HTTP_204_NO_CONTENT)
def unregister_push_token(db: DbSession, current_user: CurrentUser, token: str = Query(...)) -> None:
    delete_push_token(db, current_user.id, token)
