from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class SkillDecision(BaseModel):
    candidate_id: UUID
    decision: Literal["accepted", "edited", "rejected"]
    competency_id: UUID | None = None
    level: int | None = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def require_replacement_for_edit(self) -> "SkillDecision":
        if self.decision == "edited" and self.competency_id is None:
            raise ValueError("edited skills require a competency_id")
        return self


class ConfirmSkillsRequest(BaseModel):
    run_id: UUID
    decisions: list[SkillDecision] = Field(default_factory=list, max_length=200)

    @field_validator("decisions")
    @classmethod
    def require_unique_candidates(
        cls, value: list[SkillDecision]
    ) -> list[SkillDecision]:
        if len({item.candidate_id for item in value}) != len(value):
            raise ValueError("Each extracted skill can only be reviewed once")
        return value


class ManualSkillRequest(BaseModel):
    competency_id: UUID
    level: int = Field(ge=1, le=5)


class TargetRolesRequest(BaseModel):
    role_ids: list[UUID] = Field(max_length=3)

    @field_validator("role_ids")
    @classmethod
    def require_unique_roles(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Target roles must be unique")
        return value


class CreateShareLinkRequest(BaseModel):
    expires_in_days: Literal[7, 14, 30, 90] = 14
    sections: list[Literal["skills", "evidence", "target_roles", "credentials"]]
    max_views: int | None = Field(default=None, ge=1, le=1000)
    require_verified_employer: bool = False

    @field_validator("sections")
    @classmethod
    def validate_sections(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("Select at least one section to share")
        if len(set(value)) != len(value):
            raise ValueError("Sections must be unique")
        return value
