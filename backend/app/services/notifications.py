from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.push_token import PushToken


def upsert_push_token(db: Session, user_id: UUID, token: str, platform: str = "expo") -> PushToken:
    existing = db.scalar(select(PushToken).where(PushToken.user_id == user_id, PushToken.token == token))
    if existing:
        existing.platform = platform
        db.commit()
        db.refresh(existing)
        return existing

    push_token = PushToken(user_id=user_id, token=token, platform=platform)
    db.add(push_token)
    db.commit()
    db.refresh(push_token)
    return push_token
