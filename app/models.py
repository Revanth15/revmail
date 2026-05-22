from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SendLog:
    id: int
    created_at: datetime
    project_id: str
    template: str
    from_email: str
    to_emails: str
    cc_emails: str
    bcc_emails: str
    subject: str
    status: str
    resend_email_id: str | None
    error_message: str | None
    idempotency_key: str | None
    request_tags: str | None
    request_ip: str | None
    user_agent: str | None

