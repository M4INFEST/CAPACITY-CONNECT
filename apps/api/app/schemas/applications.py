from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ApplicationResumeLine(BaseModel):
    text: str = Field(min_length=3, max_length=1200)
    claim_id: UUID | None = None
    approved_by_learner: bool

    @field_validator("text")
    @classmethod
    def trim_line(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Resume lines cannot be blank.")
        return normalized


class ApplicationSubmission(BaseModel):
    resume_lines: list[ApplicationResumeLine] = Field(min_length=1, max_length=50)
    cover_letter: str | None = Field(default=None, max_length=8000)
    selected_credential_ids: list[UUID] = Field(default_factory=list, max_length=100)
    share_profile_consent: Literal[True]
    extra_answers: dict[UUID, Any] = Field(default_factory=dict)

    @field_validator("cover_letter")
    @classmethod
    def trim_cover_letter(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ApplicationStatusUpdate(BaseModel):
    status: Literal["heard_back", "interview", "offer", "no_reply"]
    note: str | None = Field(default=None, max_length=500)
