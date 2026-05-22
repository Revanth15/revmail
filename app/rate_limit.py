from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlite3 import Connection

from fastapi import HTTPException, status

from app.config import ProjectConfig


COUNTED_STATUSES = ("sent", "failed", "rejected")


def enforce_rate_limits(conn: Connection, project: ProjectConfig) -> None:
    # This SQLite rate limiter is appropriate for one Fly.io machine. If this
    # service scales to multiple machines, move rate limiting to Redis or Postgres.
    now = datetime.now(timezone.utc)
    minute_start = now - timedelta(minutes=1)
    day_start = now - timedelta(days=1)

    minute_count = _count_since(conn, project.project_id, minute_start)
    if minute_count >= project.minute_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Project minute email limit exceeded",
        )

    day_count = _count_since(conn, project.project_id, day_start)
    if day_count >= project.daily_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Project daily email limit exceeded",
        )


def _count_since(conn: Connection, project_id: str, since: datetime) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM send_logs
        WHERE project_id = ?
          AND created_at >= ?
          AND status IN ('sent', 'failed', 'rejected')
        """,
        (project_id, since.isoformat()),
    ).fetchone()
    return int(row["count"])

