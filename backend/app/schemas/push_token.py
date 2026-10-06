from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PushTokenCreate(BaseModel):
    token: str
    platform: str = "expo"
    # Notifications & Communication System Phase 14 — Push Token Domain.
    # Optional: a client that doesn't send one still works exactly as
    # before (see upsert_push_token's own fallback matching).
    device_identifier: str | None = None


class PushTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    token: str
    platform: str
    device_identifier: str | None
    is_active: bool
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime
