from __future__ import annotations

import hashlib
import os
import secrets


def main() -> None:
    pepper = os.environ.get("API_KEY_PEPPER")
    if not pepper:
        raise SystemExit("API_KEY_PEPPER must be set before generating an API key hash")
    raw_api_key = "egw_live_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256((raw_api_key + pepper).encode("utf-8")).hexdigest()
    print(f"Raw API key: {raw_api_key}")
    print(f"SHA-256 hash: {key_hash}")


if __name__ == "__main__":
    main()

