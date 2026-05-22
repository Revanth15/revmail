from __future__ import annotations

from typing import Any

import resend

from app.config import get_settings


class ResendSendError(RuntimeError):
    pass


def configure_resend() -> None:
    settings = get_settings()
    if settings.resend_api_key:
        resend.api_key = settings.resend_api_key


def send_email(payload: dict[str, Any]) -> str:
    configure_resend()
    try:
        response = resend.Emails.send(payload)
    except Exception as exc:  # noqa: BLE001 - SDK exceptions vary by version.
        raise ResendSendError(str(exc)) from exc

    if isinstance(response, dict):
        email_id = response.get("id")
    else:
        email_id = getattr(response, "id", None)
    if not email_id:
        raise ResendSendError("Resend did not return an email id")
    return str(email_id)

