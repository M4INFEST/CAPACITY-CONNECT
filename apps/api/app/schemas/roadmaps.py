from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class RoadmapRequest(BaseModel):
    role_id: UUID
    weekly_study_hours: float = Field(ge=0.5, le=80)
    budget_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    strategy: Literal["fastest", "cheapest"] = "fastest"
    target_finish_date: date | None = None

    @model_validator(mode="after")
    def finish_date_must_be_future(self) -> "RoadmapRequest":
        if self.target_finish_date is not None and self.target_finish_date < date.today():
            raise ValueError("Target finish date must be today or later")
        return self
