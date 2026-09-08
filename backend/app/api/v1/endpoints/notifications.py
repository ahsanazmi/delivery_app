from fastapi import APIRouter

from app.api.v1.deps import CurrentUser, DbSession
from app.schemas.push_token import PushTokenCreate, PushTokenRead
from app.services.notifications import upsert_push_token

router = APIRouter()


@router.post("/register", response_model=PushTokenRead)
def register_push_token(payload: PushTokenCreate, db: DbSession, current_user: CurrentUser) -> PushTokenRead:
    return upsert_push_token(db, current_user.id, payload.token, payload.platform)
