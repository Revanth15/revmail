from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from jinja2 import Environment, FileSystemLoader, select_autoescape


TEMPLATE_DIR = Path(__file__).parent

REQUIRED_VARIABLES = {
    "urgent_error": {"app_name", "environment", "severity", "title", "message", "timestamp"},
    "status_update": {"app_name", "title", "message", "timestamp"},
}

env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_template(template_name: str, variables: dict[str, Any]) -> tuple[str, str]:
    required = REQUIRED_VARIABLES.get(template_name)
    if required is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown template")
    missing = sorted(key for key in required if not variables.get(key))
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Missing required template variables: {', '.join(missing)}",
        )

    if template_name == "urgent_error":
        subject = f"[URGENT] {variables['app_name']}: {variables['title']}"
    else:
        subject = f"{variables['app_name']}: {variables['title']}"

    template = env.get_template(f"{template_name}.html")
    return subject, template.render(**variables)

