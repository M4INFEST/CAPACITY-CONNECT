import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


EvidenceTier = Literal["self_check", "verified"]
AssessmentQuestionType = Literal[
    "multiple_choice", "multi_select", "short_answer", "scenario", "code_task"
]


class AssessmentStartRequest(BaseModel):
    evidence_tier: EvidenceTier = "self_check"


class AssessmentResponseRequest(BaseModel):
    answer: Any = None
    learner_confidence: int = Field(ge=1, le=5)
    dont_know: bool = False
    finalize: bool = False

    @model_validator(mode="after")
    def require_answer_when_known(self) -> "AssessmentResponseRequest":
        if not self.dont_know and self.answer is None:
            raise ValueError("Provide an answer or choose I don't know")
        return self


class AssessmentPracticeRequest(BaseModel):
    answer: Any

    @model_validator(mode="after")
    def require_practice_answer(self) -> "AssessmentPracticeRequest":
        if self.answer is None:
            raise ValueError("Provide an answer")
        if len(json.dumps(self.answer)) > 10_000:
            raise ValueError("Answer is too large")
        return self


class AssessmentSubmitRequest(BaseModel):
    explanation: str = Field(default="", max_length=5000)

    @field_validator("explanation")
    @classmethod
    def normalize_explanation(cls, value: str) -> str:
        return value.strip()


class AssessmentEventRequest(BaseModel):
    event_type: Literal["tab_hidden", "tab_visible", "focus_lost"]


class AssessmentPolicyRequest(BaseModel):
    attempts_per_week: int = Field(ge=1, le=50)


class AssessmentQuestionDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    moderation_note: str = Field(min_length=3, max_length=2000)

    @field_validator("moderation_note")
    @classmethod
    def normalize_moderation_note(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Add a moderation note")
        return normalized


class AssessmentCreateRequest(BaseModel):
    course_version_id: UUID
    title: str = Field(min_length=2, max_length=250)
    time_limit_minutes: int = Field(default=30, ge=5, le=180)
    min_questions: int = Field(default=5, ge=1, le=50)
    max_questions: int = Field(default=10, ge=1, le=100)
    target_level: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def validate_question_bounds(self) -> "AssessmentCreateRequest":
        if self.min_questions > self.max_questions:
            raise ValueError("Minimum question count cannot exceed the maximum")
        return self

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()


class AssessmentQuestionRequest(BaseModel):
    competency_id: UUID
    question_type: AssessmentQuestionType
    prompt: str = Field(min_length=10, max_length=10_000)
    options: list[Any] = Field(default_factory=list, max_length=20)
    answer_key: Any
    explanation: str | None = Field(default=None, max_length=5000)
    difficulty_level: int = Field(ge=1, le=5)
    estimated_time_seconds: int = Field(default=90, ge=10, le=3600)

    @model_validator(mode="after")
    def validate_question_format(self) -> "AssessmentQuestionRequest":
        if self.question_type in {"multiple_choice", "multi_select"} and len(self.options) < 2:
            raise ValueError("Choice questions need at least two options")
        if self.question_type == "multiple_choice" and isinstance(self.answer_key, list):
            raise ValueError("A multiple-choice question must have one correct answer")
        if self.question_type == "multi_select" and not isinstance(self.answer_key, list):
            raise ValueError("A multi-select question must have a list of correct answers")
        if self.question_type in {"multiple_choice", "multi_select"}:
            values = [
                item.get("value", item.get("id", item.get("label", item.get("text"))))
                if isinstance(item, dict)
                else item
                for item in self.options
            ]
            if self.question_type == "multiple_choice" and not any(
                value == self.answer_key for value in values
            ):
                raise ValueError("Correct answer must match one of the options")
            if self.question_type == "multi_select" and any(
                value not in values for value in self.answer_key
            ):
                raise ValueError("Every correct answer must match an option")
        if not self.prompt.strip():
            raise ValueError("Question prompt cannot be blank")
        if len(json.dumps({"options": self.options, "answer_key": self.answer_key})) > 20_000:
            raise ValueError("Question options and answer key are too large")
        return self

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return value.strip()

    @field_validator("explanation")
    @classmethod
    def normalize_explanation(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None
