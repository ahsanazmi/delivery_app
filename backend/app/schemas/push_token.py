from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PushTokenCreate(BaseModel):
    token: str
    platform: str = "expo"


class PushTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    token: str
    platform: str
    created_at: datetime
