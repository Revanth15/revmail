from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger(__name__)


TemplateName = Literal["urgent_error", "status_update", "custom"]


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.:-]+$")
    api_key_hash: str = Field(min_length=64, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    default_from: str = Field(min_length=3, max_length=320)
    allowed_from: list[str] = Field(default_factory=list)
    allowed_templates: list[TemplateName] = Field(default_factory=list)
    allow_custom_html: bool = False
    allowed_recipients: list[str] = Field(default_factory=list)
    daily_limit: int = Field(gt=0)
    minute_limit: int = Field(gt=0)

    @field_validator("api_key_hash")
    @classmethod
    def normalize_hash(cls, value: str) -> str:
        normalized = value.lower()
        if any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("api_key_hash must be a lowercase SHA-256 hex digest")
        return normalized

    @field_validator("allowed_from")
    @classmethod
    def allowed_from_must_include_default(cls, value: list[str], info) -> list[str]:
        default_from = info.data.get("default_from")
        if default_from and default_from not in value:
            raise ValueError("allowed_from must include default_from")
        return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    resend_api_key: str | None = Field(default=None, alias="RESEND_API_KEY")
    api_key_pepper: str | None = Field(default=None, alias="API_KEY_PEPPER")
    projects_json: str | None = Field(default=None, alias="PROJECTS_JSON")
    database_url: str = Field(default="sqlite:////data/email_gateway.db", alias="DATABASE_URL")
    default_region: str = Field(default="sin", alias="DEFAULT_REGION")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    app_env: str = Field(default="production", alias="APP_ENV")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def parse_projects(projects_json: str | None) -> dict[str, ProjectConfig]:
    if not projects_json:
        raise RuntimeError("PROJECTS_JSON is required and must contain at least one project")
    try:
        raw_projects = json.loads(projects_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"PROJECTS_JSON is invalid JSON: {exc.msg}") from exc
    if not isinstance(raw_projects, list) or not raw_projects:
        raise RuntimeError("PROJECTS_JSON must be a non-empty JSON array")
    try:
        projects = [ProjectConfig.model_validate(item) for item in raw_projects]
    except ValidationError as exc:
        raise RuntimeError(f"PROJECTS_JSON failed validation: {exc}") from exc

    by_id: dict[str, ProjectConfig] = {}
    seen_hashes: set[str] = set()
    for project in projects:
        if project.project_id in by_id:
            raise RuntimeError(f"Duplicate project_id in PROJECTS_JSON: {project.project_id}")
        if project.api_key_hash in seen_hashes:
            raise RuntimeError("Duplicate api_key_hash in PROJECTS_JSON")
        by_id[project.project_id] = project
        seen_hashes.add(project.api_key_hash)
    return by_id


def validate_startup_settings(settings: Settings) -> None:
    missing = [
        name
        for name, value in {
            "RESEND_API_KEY": settings.resend_api_key,
            "API_KEY_PEPPER": settings.api_key_pepper,
            "PROJECTS_JSON": settings.projects_json,
        }.items()
        if not value
    ]
    if missing:
        message = (
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". For local development, create a .env file from .env.example."
        )
        if settings.is_production:
            raise RuntimeError(message)
        logger.warning(message)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    configure_logging(settings.log_level)
    validate_startup_settings(settings)
    return settings


@lru_cache
def get_projects() -> dict[str, ProjectConfig]:
    settings = get_settings()
    return parse_projects(settings.projects_json)


def clear_settings_cache() -> None:
    get_settings.cache_clear()
    get_projects.cache_clear()

