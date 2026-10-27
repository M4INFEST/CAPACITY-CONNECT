from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class JobAlertRequest(BaseModel):
    role_id: UUID | None = None
    location: str | None = Field(default=None, max_length=200)
    job_type: Literal["full_time", "part_time", "contract", "internship"] | None = None
    min_salary_cents: int | None = Field(default=None, ge=0, le=10_000_000_000)
    competency_ids: list[UUID] = Field(default_factory=list, max_length=50)
    enabled: bool = True

    @field_validator("location")
    @classmethod
    def normalize_location(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_alert_filter(self) -> "JobAlertRequest":
        if not any((self.role_id, self.location, self.job_type, self.competency_ids)):
            raise ValueError("Set at least one role, location, job type, or skill filter.")
        return self


class ExternalApplicationReport(BaseModel):
    applied_externally: bool
    external_url: HttpUrl

    @field_validator("external_url")
    @classmethod
    def external_url_requires_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("External application URLs must use HTTPS.")
        return value


class InterviewEvaluationRequest(BaseModel):
    question: str = Field(min_length=5, max_length=1000)
    user_answer: str = Field(min_length=2, max_length=5000)
    required_skill: str = Field(default="Core Competencies", max_length=150)

