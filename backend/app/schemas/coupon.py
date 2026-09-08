from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.coupon import DiscountType


class CouponCreate(BaseModel):
    code: str = Field(min_length=3, max_length=64)
    discount_type: DiscountType
    discount_value: Decimal = Field(gt=0)
    min_order: Decimal = Field(default=Decimal("0.00"), ge=0)
    max_discount: Decimal | None = Field(default=None, ge=0)
    start_date: datetime | None = None
    end_date: datetime | None = None
    usage_limit: int | None = Field(default=None, ge=1)
    is_active: bool = True


class CouponRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    discount_type: DiscountType
    discount_value: Decimal
    min_order: Decimal
    max_discount: Decimal | None
    start_date: datetime | None
    end_date: datetime | None
    usage_limit: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
