from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class CredentialRevocationRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("A revocation reason is required")
        return normalized


class CredentialExpiryRequest(BaseModel):
    expires_at: datetime | None
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("A reason is required")
        return normalized
