from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from sqlite3 import Connection, IntegrityError
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status

from app.auth import AuthenticatedProject, authenticate_project
from app.config import ProjectConfig, get_projects, get_settings
from app.database import get_db, init_db
from app.rate_limit import enforce_rate_limits
from app.resend_service import ResendSendError, configure_resend, send_email
from app.schemas import EmailLogResponse, EmailLogsResponse, EmailSendRequest, EmailSendResponse, HealthResponse
from app.templates.renderer import render_template


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    get_projects()
    init_db()
    configure_resend()
    logger.info("email_gateway_started env=%s region=%s", settings.app_env, settings.default_region)
    yield


app = FastAPI(title="Email Gateway", version="1.0.0", lifespan=lifespan)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(env=settings.app_env, timestamp=datetime.now(timezone.utc))


@app.post("/v1/email/send", response_model=EmailSendResponse)
def send_email_endpoint(
    payload: EmailSendRequest,
    request: Request,
    auth: AuthenticatedProject = Depends(authenticate_project),
) -> EmailSendResponse:
    project = auth.project
    if payload.project_id != project.project_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token is not valid for this project_id")

    request_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    with get_db() as conn:
        duplicate = find_successful_idempotent_send(conn, payload.project_id, payload.idempotency_key)
        if duplicate:
            return EmailSendResponse(
                success=True,
                email_id=duplicate["resend_email_id"],
                project_id=payload.project_id,
                template=payload.template,
                status="duplicate",
            )

        try:
            enforce_rate_limits(conn, project)
            from_email, subject, html = validate_and_render(project, payload)
            resend_payload = build_resend_payload(payload, from_email, subject, html)
        except HTTPException as exc:
            log_send(
                conn=conn,
                payload=payload,
                from_email=payload.from_email or project.default_from,
                subject=payload.subject or "",
                status="rejected",
                error_message=str(exc.detail),
                request_ip=request_ip,
                user_agent=user_agent,
            )
            raise

        try:
            email_id = send_email(resend_payload)
        except ResendSendError as exc:
            logger.warning(
                "resend_send_failed project_id=%s template=%s error=%s",
                payload.project_id,
                payload.template,
                str(exc),
            )
            log_send(
                conn=conn,
                payload=payload,
                from_email=from_email,
                subject=subject,
                status="failed",
                error_message="Email provider rejected the message",
                request_ip=request_ip,
                user_agent=user_agent,
            )
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to send email") from exc

        try:
            log_send(
                conn=conn,
                payload=payload,
                from_email=from_email,
                subject=subject,
                status="sent",
                resend_email_id=email_id,
                request_ip=request_ip,
                user_agent=user_agent,
            )
        except IntegrityError:
            duplicate = find_successful_idempotent_send(conn, payload.project_id, payload.idempotency_key)
            if duplicate:
                return EmailSendResponse(
                    success=True,
                    email_id=duplicate["resend_email_id"],
                    project_id=payload.project_id,
                    template=payload.template,
                    status="duplicate",
                )
            raise

        return EmailSendResponse(
            success=True,
            email_id=email_id,
            project_id=payload.project_id,
            template=payload.template,
            status="sent",
        )


@app.get("/v1/email/logs", response_model=EmailLogsResponse)
def get_logs(
    project_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
    auth: AuthenticatedProject = Depends(authenticate_project),
) -> EmailLogsResponse:
    project = auth.project
    if project_id and project_id != project.project_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token cannot access that project")

    clauses = ["project_id = ?"]
    params: list[Any] = [project.project_id]
    if status_filter:
        clauses.append("status = ?")
        params.append(status_filter)
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM send_logs
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    return EmailLogsResponse(logs=[row_to_log_response(row) for row in rows])


def validate_and_render(project: ProjectConfig, payload: EmailSendRequest) -> tuple[str, str, str]:
    if payload.template not in project.allowed_templates:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Template is not allowed for this project")

    from_email = payload.from_email or project.default_from
    if from_email not in project.allowed_from:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="from address is not allowed")

    enforce_allowed_recipients(project, payload)

    if payload.template == "custom":
        if not project.allow_custom_html:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Custom HTML is disabled for this project")
        if not payload.subject:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="subject is required for custom emails")
        if not payload.html:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="html is required for custom emails")
        return from_email, payload.subject, payload.html

    default_subject, html = render_template(payload.template, payload.variables)
    return from_email, payload.subject or default_subject, html


def enforce_allowed_recipients(project: ProjectConfig, payload: EmailSendRequest) -> None:
    if not project.allowed_recipients:
        return
    allowed = {email.lower() for email in project.allowed_recipients}
    recipients = [*payload.to, *payload.cc, *payload.bcc]
    blocked = [str(email) for email in recipients if str(email).lower() not in allowed]
    if blocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="One or more recipients are not allowed for this project",
        )


def build_resend_payload(payload: EmailSendRequest, from_email: str, subject: str, html: str) -> dict[str, Any]:
    resend_payload: dict[str, Any] = {
        "from": from_email,
        "to": [str(email) for email in payload.to],
        "subject": subject,
        "html": html,
    }
    if payload.cc:
        resend_payload["cc"] = [str(email) for email in payload.cc]
    if payload.bcc:
        resend_payload["bcc"] = [str(email) for email in payload.bcc]
    if payload.reply_to:
        resend_payload["reply_to"] = str(payload.reply_to)
    if payload.text:
        resend_payload["text"] = payload.text
    if payload.tags:
        resend_payload["tags"] = [{"name": key, "value": value} for key, value in payload.tags.items()]
    if payload.idempotency_key:
        resend_payload["headers"] = {"Idempotency-Key": payload.idempotency_key}
    return resend_payload


def find_successful_idempotent_send(conn: Connection, project_id: str, idempotency_key: str | None):
    if not idempotency_key:
        return None
    return conn.execute(
        """
        SELECT resend_email_id, status
        FROM send_logs
        WHERE project_id = ?
          AND idempotency_key = ?
          AND status = 'sent'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (project_id, idempotency_key),
    ).fetchone()


def log_send(
    *,
    conn: Connection,
    payload: EmailSendRequest,
    from_email: str,
    subject: str,
    status: str,
    resend_email_id: str | None = None,
    error_message: str | None = None,
    request_ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO send_logs (
            created_at, project_id, template, from_email, to_emails, cc_emails,
            bcc_emails, subject, status, resend_email_id, error_message,
            idempotency_key, request_tags, request_ip, user_agent
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            payload.project_id,
            payload.template,
            from_email,
            json.dumps([str(email) for email in payload.to]),
            json.dumps([str(email) for email in payload.cc]),
            json.dumps([str(email) for email in payload.bcc]),
            subject,
            status,
            resend_email_id,
            error_message,
            payload.idempotency_key,
            json.dumps(payload.tags),
            request_ip,
            user_agent,
        ),
    )


def row_to_log_response(row) -> EmailLogResponse:
    return EmailLogResponse(
        id=row["id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        project_id=row["project_id"],
        template=row["template"],
        from_email=row["from_email"],
        to_emails=json.loads(row["to_emails"]),
        cc_emails=json.loads(row["cc_emails"]),
        bcc_emails=json.loads(row["bcc_emails"]),
        subject=row["subject"],
        status=row["status"],
        resend_email_id=row["resend_email_id"],
        error_message=row["error_message"],
        idempotency_key=row["idempotency_key"],
        request_tags=json.loads(row["request_tags"] or "{}"),
        request_ip=row["request_ip"],
        user_agent=row["user_agent"],
    )
