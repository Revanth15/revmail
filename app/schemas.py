from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


TemplateName = Literal["urgent_error", "status_update", "custom"]


class EmailSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=80)
    template: TemplateName
    to: list[EmailStr] = Field(min_length=1)
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)
    from_email: str | None = Field(default=None, alias="from", min_length=3, max_length=320)
    reply_to: EmailStr | None = None
    subject: str | None = Field(default=None, max_length=200)
    variables: dict[str, Any] = Field(default_factory=dict)
    html: str | None = Field(default=None, max_length=250_000)
    text: str | None = Field(default=None, max_length=50_000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20:
            raise ValueError("tags may contain at most 20 items")
        for key, tag_value in value.items():
            if len(key) > 40 or len(tag_value) > 120:
                raise ValueError("tag keys must be <= 40 chars and values <= 120 chars")
        return value

    @model_validator(mode="after")
    def validate_recipient_count(self) -> "EmailSendRequest":
        total = len(self.to) + len(self.cc) + len(self.bcc)
        if total > 10:
            raise ValueError("Maximum recipients across to, cc, and bcc is 10")
        return self


class EmailSendResponse(BaseModel):
    success: bool
    email_id: str
    project_id: str
    template: TemplateName
    status: Literal["sent", "duplicate"]


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "email-gateway"
    env: str
    timestamp: datetime


class EmailLogResponse(BaseModel):
    id: int
    created_at: datetime
    project_id: str
    template: str
    from_email: str
    to_emails: list[str]
    cc_emails: list[str]
    bcc_emails: list[str]
    subject: str
    status: str
    resend_email_id: str | None
    error_message: str | None
    idempotency_key: str | None
    request_tags: dict[str, str]
    request_ip: str | None
    user_agent: str | None


class EmailLogsResponse(BaseModel):
    logs: list[EmailLogResponse]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

