# Email Gateway

A lightweight internal FastAPI service for sending application email through Resend. Apps call this gateway with a project API key instead of embedding Resend credentials directly.

## Why Use This Instead Of Resend Directly

- Centralizes Resend credentials in one deployable service.
- Gives each app its own API key, sender allowlist, template allowlist, and rate limits.
- Keeps local SQLite send logs for debugging and audit trails.
- Supports reusable incident and status templates while still allowing trusted server-side custom HTML projects.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`, then run:

```bash
uvicorn app.main:app --reload
```

Docker:

```bash
docker build -t email-gateway .
docker run -p 8000:8000 --env-file .env email-gateway
```

## Generate API Key

Set the same pepper you will use in the service:

```bash
export API_KEY_PEPPER="replace_with_long_random_secret"
python scripts/generate_api_key.py
```

Store the raw API key only in the calling app. Put only the printed SHA-256 hash in `PROJECTS_JSON`.

## Example PROJECTS_JSON

```json
[
  {
    "project_id": "bussing",
    "name": "BusSing",
    "api_key_hash": "replace_with_generated_hash",
    "default_from": "BusSing <alerts@example.com>",
    "allowed_from": ["BusSing <alerts@example.com>"],
    "allowed_templates": ["urgent_error", "status_update"],
    "allow_custom_html": false,
    "allowed_recipients": [],
    "daily_limit": 500,
    "minute_limit": 20
  },
  {
    "project_id": "hackathon",
    "name": "Hackathon Projects",
    "api_key_hash": "replace_with_generated_hash",
    "default_from": "Revanth Apps <hello@example.com>",
    "allowed_from": ["Revanth Apps <hello@example.com>"],
    "allowed_templates": ["urgent_error", "status_update", "custom"],
    "allow_custom_html": true,
    "allowed_recipients": [],
    "daily_limit": 200,
    "minute_limit": 10
  }
]
```

## Send Urgent Error

```bash
curl -X POST https://your-app.fly.dev/v1/email/send \
  -H "Authorization: Bearer egw_live_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "bussing",
    "template": "urgent_error",
    "to": ["admin@example.com"],
    "variables": {
      "app_name": "BusSing",
      "environment": "production",
      "severity": "critical",
      "title": "LTA API failure",
      "message": "Bus arrival endpoint returned repeated 503 errors.",
      "timestamp": "2026-05-23T12:00:00+08:00",
      "route": "/bustiming",
      "request_id": "req_123"
    },
    "idempotency_key": "incident-req-123"
  }'
```

## Send Status Update

```bash
curl -X POST https://your-app.fly.dev/v1/email/send \
  -H "Authorization: Bearer egw_live_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "bussing",
    "template": "status_update",
    "to": ["user@example.com"],
    "variables": {
      "app_name": "BusSing",
      "title": "Service restored",
      "message": "Bus arrival timings are back to normal.",
      "timestamp": "2026-05-23T12:30:00+08:00",
      "status": "resolved"
    }
  }'
```

## Send Custom HTML

```bash
curl -X POST https://your-app.fly.dev/v1/email/send \
  -H "Authorization: Bearer egw_live_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "hackathon",
    "template": "custom",
    "to": ["user@example.com"],
    "subject": "Welcome to our hackathon app",
    "html": "<h1>Welcome!</h1><p>This is a fully custom email.</p>",
    "text": "Welcome! This is a fully custom email."
  }'
```

## Logs

```bash
curl "https://your-app.fly.dev/v1/email/logs?limit=50" \
  -H "Authorization: Bearer egw_live_xxx"
```

Logs are scoped to the authenticated project. A token for one project cannot read another project's logs.

## Fly.io Deployment

```bash
fly volumes create email_gateway_data --region sin --size 1
fly secrets set RESEND_API_KEY=...
fly secrets set API_KEY_PEPPER=...
fly secrets set PROJECTS_JSON='[...]'
fly deploy
```

SQLite is stored on the mounted volume at `/data/email_gateway.db` by default.

## Security Notes

- Every request must include `Authorization: Bearer <project_api_key>`.
- `PROJECTS_JSON` must contain hashed API keys only: `sha256(raw_api_key + API_KEY_PEPPER)`.
- Raw API keys are never logged.
- Sender addresses are restricted by `allowed_from`.
- Templates are restricted by `allowed_templates`.
- If `allowed_recipients` is non-empty, every `to`, `cc`, and `bcc` recipient must be in that allowlist.
- Custom HTML is intentionally not sanitized. Enable `allow_custom_html` only for trusted server-side callers. Keep it disabled for client or mobile callers.

## Scaling Notes

This v1 service is designed for one Fly.io machine with SQLite-backed logs, idempotency, and rate limiting. If you scale to multiple machines, move rate limiting and idempotency coordination to Redis or Postgres, and consider moving logs to Postgres for stronger cross-machine consistency.

