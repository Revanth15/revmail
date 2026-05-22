from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import Settings, get_settings


def sqlite_path_from_url(database_url: str) -> str:
    if database_url.startswith("sqlite:///"):
        return database_url.removeprefix("sqlite:///")
    if database_url.startswith("sqlite://"):
        return database_url.removeprefix("sqlite://")
    raise ValueError("Only sqlite database URLs are supported for v1")


def get_database_path(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return sqlite_path_from_url(settings.database_url)


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    path = get_database_path()
    db_path = Path(path)
    if db_path.parent:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS send_logs (
                id INTEGER PRIMARY KEY,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                project_id TEXT NOT NULL,
                template TEXT NOT NULL,
                from_email TEXT NOT NULL,
                to_emails TEXT NOT NULL,
                cc_emails TEXT NOT NULL,
                bcc_emails TEXT NOT NULL,
                subject TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('sent', 'failed', 'rejected', 'duplicate')),
                resend_email_id TEXT NULL,
                error_message TEXT NULL,
                idempotency_key TEXT NULL,
                request_tags TEXT NULL,
                request_ip TEXT NULL,
                user_agent TEXT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_send_logs_idempotency_sent
            ON send_logs(project_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL AND status = 'sent'
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_send_logs_project_created ON send_logs(project_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_send_logs_rate ON send_logs(project_id, created_at, status)")

