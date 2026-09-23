from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.notification import NotificationType


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: NotificationType
    title: str
    body: str
    order_id: UUID | None
    is_read: bool
    created_at: datetime


class MarkAllReadResponse(BaseModel):
    updated: int


class PromotionalBroadcastCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=1000)


class PromotionalBroadcastResult(BaseModel):
    notified_customers: int
