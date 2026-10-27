from typing import Literal
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


LearningFormat = Literal["self_paced", "instructor_led", "blended"]


class LearningPreferencesRequest(BaseModel):
    weekly_study_hours: float = Field(ge=0.5, le=80)
    budget_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    learning_format: LearningFormat
    prioritize_paid: bool = False


class WishlistRequest(BaseModel):
    course_version_id: UUID


class CompareCoursesRequest(BaseModel):
    course_version_ids: list[UUID] = Field(min_length=2, max_length=3)

    @field_validator("course_version_ids")
    @classmethod
    def require_unique_courses(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Choose each course only once")
        return value


class ExternalCourseRequest(BaseModel):
    title: str = Field(min_length=2, max_length=250)
    description: str | None = Field(default=None, max_length=10_000)
    provider: str = Field(min_length=2, max_length=120)
    provider_domain: str = Field(min_length=4, max_length=253)
    course_url: HttpUrl
    duration_hours: float | None = Field(default=None, gt=0, le=100_000)
    price_cents: int = Field(default=0, ge=0, le=100_000_000)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    language: str = Field(default="en", min_length=2, max_length=12)
    skills: dict[UUID, int] = Field(min_length=1, max_length=50)

    @field_validator("provider_domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        return value.strip().lower().removeprefix("www.")

    @field_validator("course_url")
    @classmethod
    def require_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("External course links must use HTTPS")
        return value


class ExternalCompletionRequest(BaseModel):
    certificate_id: str = Field(min_length=2, max_length=200)
    certificate_url: HttpUrl

    @field_validator("certificate_id")
    @classmethod
    def normalize_certificate_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Certificate ID is required")
        return normalized

    @field_validator("certificate_url")
    @classmethod
    def require_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("Certificate links must use HTTPS")
        return value


class ExternalCompletionDecision(BaseModel):
    decision: Literal["verified", "rejected"]
    review_reason: str = Field(min_length=3, max_length=2000)


class CourseEnrollmentRequest(BaseModel):
    sponsorship_code: str | None = Field(default=None, min_length=6, max_length=80)
    acknowledge_prerequisites: bool = False

    @field_validator("sponsorship_code")
    @classmethod
    def normalize_sponsorship_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None


class LessonHeartbeatRequest(BaseModel):
    last_position_seconds: int = Field(ge=0, le=86_400)


class LessonNotesRequest(BaseModel):
    notes: str = Field(max_length=20_000)


class CheckpointAnswerRequest(BaseModel):
    answer: str | int | bool | list[str]

    @field_validator("answer")
    @classmethod
    def bound_answer_size(cls, value: str | int | bool | list[str]) -> str | int | bool | list[str]:
        if isinstance(value, str) and len(value) > 2000:
            raise ValueError("Answer must be at most 2,000 characters")
        if isinstance(value, list) and (
            len(value) > 100 or any(len(item) > 2000 for item in value)
        ):
            raise ValueError("Answer selection is too large")
        return value


class LearningSubmissionRequest(BaseModel):
    submission_type: Literal["lab", "project"]
    lesson_id: UUID | None = None
    title: str = Field(min_length=2, max_length=250)
    submission_url: HttpUrl | None = None
    submission_text: str | None = Field(default=None, min_length=1, max_length=20_000)

    @field_validator("submission_url")
    @classmethod
    def require_https_submission_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and value.scheme != "https":
            raise ValueError("Submission links must use HTTPS")
        return value

    @field_validator("submission_text")
    @classmethod
    def normalize_submission_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def require_submission_content(self) -> "LearningSubmissionRequest":
        if self.submission_url is None and self.submission_text is None:
            raise ValueError("Provide a project link or written submission")
        return self


class DiscussionPostRequest(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    parent_id: UUID | None = None

    @field_validator("body")
    @classmethod
    def normalize_discussion_body(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message cannot be blank")
        return normalized


class SubmissionDecisionRequest(BaseModel):
    decision: Literal["reviewed", "changes_requested"]
    trainer_feedback: str = Field(min_length=2, max_length=5000)


class SponsorshipCodeRequest(BaseModel):
    course_version_id: UUID | None = None
    max_uses: int = Field(ge=1, le=100_000)
    expires_at: datetime | None = None
