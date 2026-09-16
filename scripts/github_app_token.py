#!/usr/bin/env python3
"""Mint and cache a short-lived GitHub App installation token."""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


APP_DIR = Path(os.environ.get("HERMES_GITHUB_APP_DIR", "/data/.hermes/github-app"))
APP_ID_FILE = APP_DIR / "app-id"
INSTALLATION_ID_FILE = APP_DIR / "installation-id"
PRIVATE_KEY_FILE = APP_DIR / "private-key.pem"
CACHE_FILE = APP_DIR / "token-cache.json"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _app_jwt(app_id: str, private_key: bytes) -> str:
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps({"iat": now - 60, "exp": now + 540, "iss": app_id}, separators=(",", ":")).encode()
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    key = serialization.load_pem_private_key(private_key, password=None)
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64url(signature)}"


def _cached_token() -> str | None:
    try:
        cache = json.loads(CACHE_FILE.read_text())
        if int(cache["expires_at_epoch"]) - 120 > int(time.time()):
            return str(cache["token"])
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return None


def _write_cache(token: str, expires_at: str) -> None:
    expires_at_epoch = int(datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp())
    APP_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="token-cache.", dir=APP_DIR)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump({"token": token, "expires_at_epoch": expires_at_epoch}, handle)
        os.replace(temp_name, CACHE_FILE)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def main() -> int:
    missing = [path for path in (APP_ID_FILE, INSTALLATION_ID_FILE, PRIVATE_KEY_FILE) if not path.is_file()]
    if missing:
        print(
            "Hermes GitHub App authentication is not configured; missing: "
            + ", ".join(path.name for path in missing),
            file=sys.stderr,
        )
        return 1

    token = _cached_token()
    if token:
        print(token)
        return 0

    app_id = APP_ID_FILE.read_text().strip()
    installation_id = INSTALLATION_ID_FILE.read_text().strip()
    jwt = _app_jwt(app_id, PRIVATE_KEY_FILE.read_bytes())
    response = httpx.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {jwt}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=20.0,
    )
    if response.status_code != 201:
        print(f"GitHub App token request failed (HTTP {response.status_code}).", file=sys.stderr)
        return 1

    payload = response.json()
    token = str(payload["token"])
    _write_cache(token, str(payload["expires_at"]))
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
