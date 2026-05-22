from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import ProjectConfig, get_projects, get_settings


security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedProject:
    project: ProjectConfig
    raw_token_hash: str


def hash_api_key(raw_api_key: str, pepper: str) -> str:
    return hashlib.sha256((raw_api_key + pepper).encode("utf-8")).hexdigest()


def authenticate_project(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> AuthenticatedProject:
    if not credentials or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()
    if not settings.api_key_pepper:
        raise HTTPException(status_code=500, detail="API key verification is not configured")

    token_hash = hash_api_key(credentials.credentials, settings.api_key_pepper)
    for project in get_projects().values():
        if hmac.compare_digest(token_hash, project.api_key_hash):
            return AuthenticatedProject(project=project, raw_token_hash=token_hash)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )

