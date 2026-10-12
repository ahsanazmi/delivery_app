from datetime import datetime
from uuid import UUID

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PushTokenCreate(BaseModel):
    # E2E Validation Phase 22 — every push goes through Expo, so only an Expo
    # push token is deliverable. Anything was accepted before: "abc", "" and
    # "ExponentPushToken[]" were stored as live tokens, and a value longer
    # than the 512-char column was an unhandled DB error (500).
    token: str = Field(max_length=512, pattern=r"^Expo(nent)?PushToken\[[^\[\]\s]+\]$")
    platform: Literal["expo", "ios", "android", "web"] = "expo"
    # Notifications & Communication System Phase 14 — Push Token Domain.
    # Optional: a client that doesn't send one still works exactly as
    # before (see upsert_push_token's own fallback matching).
    device_identifier: str | None = Field(default=None, max_length=255)


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
