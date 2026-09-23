from datetime import time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class OperatingHourEntry(BaseModel):
    day_of_week: int = Field(ge=0, le=6, description="0=Monday .. 6=Sunday")
    is_closed: bool = False
    open_time: time | None = None
    close_time: time | None = None

    @model_validator(mode="after")
    def _validate_window(self) -> "OperatingHourEntry":
        if self.is_closed:
            return self
        if self.open_time is None or self.close_time is None:
            raise ValueError("open_time and close_time are required unless the day is marked closed")
        if self.open_time >= self.close_time:
            raise ValueError("open_time must be before close_time (overnight hours aren't supported yet)")
        return self


class OperatingHourRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    day_of_week: int
    day_name: str = ""
    is_closed: bool
    open_time: time | None
    close_time: time | None

    @model_validator(mode="after")
    def _fill_day_name(self) -> "OperatingHourRead":
        if not self.day_name:
            self.day_name = DAY_NAMES[self.day_of_week]
        return self


class OperatingHoursUpdate(BaseModel):
    hours: list[OperatingHourEntry]

    @model_validator(mode="after")
    def _validate_full_week(self) -> "OperatingHoursUpdate":
        days = [entry.day_of_week for entry in self.hours]
        if sorted(days) != list(range(7)):
            raise ValueError("hours must contain exactly one entry for each day of the week (0-6)")
        return self


class RestaurantHoursResponse(BaseModel):
    restaurant_id: UUID
    hours: list[OperatingHourRead]


class RestaurantStatusResponse(BaseModel):
    restaurant_id: UUID
    is_open: bool
    is_accepting_orders: bool
    hours_configured: bool
    today: OperatingHourRead | None


class RestaurantStatusUpdate(BaseModel):
    is_open: bool
