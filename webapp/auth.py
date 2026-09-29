"""Shared-password login for team deployments.

Deliberately small: one password in APP_PASSWORD, an HMAC-signed session cookie,
no user database. Enough to keep a deployed instance from being an open scraper
for anyone who finds the URL.

If APP_PASSWORD is unset, auth is disabled - fine on localhost, refused when the
server binds a public interface (see run_web.py, and REQUIRE_AUTH in server.py).
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import HTTPException, Request

COOKIE_NAME = "gms_session"
SESSION_DAYS = 7

_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()

# A generated secret means sessions die on restart; that's a warning, not a fault.
_SECRET = os.environ.get("APP_SECRET", "").strip() or secrets.token_hex(32)
SECRET_IS_EPHEMERAL = not os.environ.get("APP_SECRET", "").strip()


def enabled() -> bool:
    return bool(_PASSWORD)


def _sign(payload: bytes) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(_SECRET.encode(), payload, hashlib.sha256).digest()
    ).decode()


def make_token() -> str:
    payload = json.dumps({"exp": int(time.time()) + SESSION_DAYS * 86400}).encode()
    body = base64.urlsafe_b64encode(payload).decode()
    return "{}.{}".format(body, _sign(payload))


def valid_token(token: str) -> bool:
    if not token or "." not in token:
        return False
    body, _, signature = token.rpartition(".")
    try:
        payload = base64.urlsafe_b64decode(body.encode())
    except Exception:
        return False
    if not hmac.compare_digest(signature, _sign(payload)):
        return False
    try:
        return json.loads(payload).get("exp", 0) > time.time()
    except Exception:
        return False


def check_password(candidate: str) -> bool:
    # Constant-time so the comparison doesn't leak the password's prefix.
    return bool(_PASSWORD) and hmac.compare_digest(candidate.strip(), _PASSWORD)


def is_authed(request: Request) -> bool:
    if not enabled():
        return True
    return valid_token(request.cookies.get(COOKIE_NAME, ""))


def require(request: Request) -> None:
    """FastAPI dependency: 401 unless the caller holds a valid session."""
    if not is_authed(request):
        raise HTTPException(401, "Sign in to use this tool.")
