from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=256)
    role: str = "trainee"
    company_name: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=500)
    industry: str | None = Field(default=None, max_length=120)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if (
            not any(char.isupper() for char in value)
            or not any(char.islower() for char in value)
            or not any(char.isdigit() for char in value)
        ):
            raise ValueError("Password must include uppercase, lowercase, and numeric characters")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if email.count("@") != 1 or any(char.isspace() for char in email):
            raise ValueError("A valid email address is required")
        local, domain = email.split("@")
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("A valid email address is required")
        return email

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {"trainee", "employer"}:
            raise ValueError("Public registration supports trainee or employer accounts")
        return value

    @field_validator("company_name")
    @classmethod
    def normalize_company_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)
    captcha_token: str | None = Field(default=None, max_length=4096)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class RegistrationResponse(BaseModel):
    id: str
    email: str
    roles: list[str]
    employer_verification_level: int | None = None
    verification_required: bool = True


class TokenResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int = 1800
    mfa_required: bool = False
    challenge_token: str | None = None
    mfa_setup_required: bool = False
    setup_token: str | None = None


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MfaEnrollmentResponse(BaseModel):
    enabled: bool = True
    recovery_codes: list[str]
    access_token: str


class EmailTokenRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class EmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class PasswordResetRequest(EmailTokenRequest):
    password: str = Field(min_length=12, max_length=256)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if (
            not any(char.isupper() for char in value)
            or not any(char.islower() for char in value)
            or not any(char.isdigit() for char in value)
        ):
            raise ValueError("Password must include uppercase, lowercase, and numeric characters")
        return value


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=128)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        normalized = value.strip().replace("-", "").replace(" ", "")
        if not normalized.isascii() or not (
            (len(normalized) == 6 and normalized.isdigit())
            or (
                len(normalized) == 32
                and all(char in "0123456789abcdefABCDEF" for char in normalized)
            )
        ):
            raise ValueError("Enter a six-digit authenticator code or a recovery code")
        return normalized


class MfaSetupRequest(BaseModel):
    password: str | None = Field(default=None, min_length=1, max_length=256)


class MfaDisableRequest(MfaSetupRequest):
    code: str = Field(min_length=6, max_length=128)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        return MfaCodeRequest(code=value).code


class MfaStatusResponse(BaseModel):
    enabled: bool
    recovery_codes_remaining: int


class GoogleOAuthExchangeRequest(BaseModel):
    code: str = Field(min_length=32, max_length=256)


class UserResponse(BaseModel):
    id: str
    email: str
    roles: list[str]
    employer_verification_level: int | None = None


class TrainerDecisionRequest(BaseModel):
    decision: str
    review_reason: str = Field(min_length=3, max_length=2000)

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, value: str) -> str:
        if value not in {"approved", "rejected", "needs_info"}:
            raise ValueError("decision must be approved, rejected, or needs_info")
        return value


class TrainerApplicationRequest(BaseModel):
    expertise: list[str] = Field(min_length=1, max_length=30)

    @field_validator("expertise")
    @classmethod
    def normalize_expertise(cls, value: list[str]) -> list[str]:
        normalized = sorted({item.strip() for item in value if item.strip()})
        if not normalized or len(normalized) > 30 or any(len(item) > 120 for item in normalized):
            raise ValueError("Provide between 1 and 30 expertise areas, each at most 120 characters")
        return normalized


class EmployerVerificationRequest(BaseModel):
    level: int = Field(ge=1, le=2)
    review_reason: str = Field(min_length=3, max_length=2000)
