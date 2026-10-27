from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


JobType = Literal["full_time", "part_time", "contract", "internship"]
QuestionType = Literal["text", "yes_no", "single_choice"]


class JobRequirementInput(BaseModel):
    competency_id: UUID
    required_level: int = Field(ge=1, le=5)
    importance: float = Field(default=1.0, ge=0, le=1)


class JobQuestionInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)
    answer_type: QuestionType
    options: list[str] = Field(default_factory=list, max_length=20)
    required: bool = False

    @field_validator("prompt")
    @classmethod
    def trim_prompt(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_options(self) -> "JobQuestionInput":
        self.options = [option.strip() for option in self.options if option.strip()]
        if self.answer_type == "single_choice" and not self.options:
            raise ValueError("Single-choice questions need at least one option.")
        if self.answer_type != "single_choice" and self.options:
            raise ValueError("Only single-choice questions can have options.")
        if len(set(self.options)) != len(self.options):
            raise ValueError("Question options must be unique.")
        return self


class EmployerJobInput(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=20, max_length=20_000)
    role_id: UUID | None = None
    location: str | None = Field(default=None, max_length=200)
    job_type: JobType | None = None
    experience_min_years: float | None = Field(default=None, ge=0, le=60)
    experience_max_years: float | None = Field(default=None, ge=0, le=60)
    salary_min_cents: int | None = Field(default=None, ge=0, le=10_000_000_000)
    salary_max_cents: int | None = Field(default=None, ge=0, le=10_000_000_000)
    salary_currency: str = Field(default="INR", min_length=3, max_length=3)
    requirements: list[JobRequirementInput] = Field(default_factory=list, max_length=50)
    questions: list[JobQuestionInput] = Field(default_factory=list, max_length=10)
    active: bool = True

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("location")
    @classmethod
    def normalize_location(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("salary_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("Salary currency must be a three-letter code.")
        return normalized

    @model_validator(mode="after")
    def validate_job(self) -> "EmployerJobInput":
        if (
            self.experience_min_years is not None
            and self.experience_max_years is not None
            and self.experience_min_years > self.experience_max_years
        ):
            raise ValueError("Minimum experience cannot exceed maximum experience.")
        if (
            self.salary_min_cents is not None
            and self.salary_max_cents is not None
            and self.salary_min_cents > self.salary_max_cents
        ):
            raise ValueError("Minimum salary cannot exceed maximum salary.")
        requirement_ids = [item.competency_id for item in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("A competency can only be listed once.")
        if not self.requirements and self.role_id is None:
            raise ValueError("Add at least one required skill or select a platform role.")
        return self


class EmployerJobActiveUpdate(BaseModel):
    active: bool


class EmployerApplicationStatusUpdate(BaseModel):
    status: Literal["shortlisted", "interview", "offer", "rejected"]
    rejection_reason: Literal["position_filled", "role_changed", "candidate_withdrew"] | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_rejection_reason(self) -> "EmployerApplicationStatusUpdate":
        if self.status == "rejected" and self.rejection_reason is None:
            raise ValueError("Choose a neutral rejection reason.")
        if self.status != "rejected" and self.rejection_reason is not None:
            raise ValueError("A rejection reason is only valid for a rejection.")
        return self


class EmployerApplicationNote(BaseModel):
    note: str = Field(default="", max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("note")
    @classmethod
    def trim_note(cls, value: str) -> str:
        return value.strip()

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if any(len(value) > 40 for value in normalized):
            raise ValueError("Tags cannot exceed 40 characters.")
        return normalized


class EmployerCompanyProfileUpdate(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    website: HttpUrl | None = None
    industry: str | None = Field(default=None, max_length=120)

    @field_validator("company_name")
    @classmethod
    def trim_company_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("industry")
    @classmethod
    def trim_industry(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class CompareApplicantsRequest(BaseModel):
    application_ids: list[UUID] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def ensure_unique_applications(self) -> "CompareApplicantsRequest":
        if len(self.application_ids) != len(set(self.application_ids)):
            raise ValueError("Choose each applicant only once.")
        return self
