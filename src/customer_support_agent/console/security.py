"""Passwords, one-time links and session cookies for the support console. Standard library only.

- Passwords: scrypt (memory-hard, OWASP-recommended), a random salt per password, compared in constant time.
- Invite / reset links: 32 random bytes; only the SHA-256 of the token is stored, so a database leak can't be
  turned into working links.
- Sessions: a signed cookie (HMAC-SHA256) holding the member ID, their session version and an expiry. Bumping
  the session version (disable, password reset) signs that person out everywhere.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import time

SCRYPT = {"n": 2**14, "r": 8, "p": 1, "maxmem": 64 * 1024 * 1024, "dklen": 32}
PASSWORD_MIN, PASSWORD_MAX = 8, 128
NAME_MIN, NAME_MAX = 2, 80
SESSION_SECONDS = 12 * 3600
INVITE_SECONDS = 72 * 3600
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """Always does the work of one hash, even for an unknown member, so timing doesn't reveal who exists."""
    try:
        _, salt_hex, digest_hex = (stored or "").split("$")
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
    except ValueError:
        salt, expected = b"0" * 16, b""
    actual = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return bool(expected) and hmac.compare_digest(actual, expected)


def new_link_token() -> tuple[str, str]:
    """(token for the link, its hash to store)."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalise_email(email: str | None) -> str | None:
    email = (email or "").strip().lower()
    return email if EMAIL.match(email) and len(email) <= 254 else None


def check_new_password(name: str | None, password: str | None, confirm: str | None, email: str) -> dict[str, str]:
    """Field -> problem, for the accept-invite form. Empty means valid."""
    problems = {}
    name = (name or "").strip()
    if not NAME_MIN <= len(name) <= NAME_MAX:
        problems["name"] = f"Enter your name ({NAME_MIN} to {NAME_MAX} characters)."
    password = password or ""
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        problems["password"] = f"Use {PASSWORD_MIN} to {PASSWORD_MAX} characters."
    elif password.strip().lower() == email.lower():
        problems["password"] = "Don't use your email as your password."
    if password != (confirm or ""):
        problems["confirm_password"] = "The passwords don't match."
    return problems


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_session(secret: str, member_id: str, session_version: int, now: float | None = None) -> str:
    payload = _b64(json.dumps({"m": member_id, "v": session_version,
                               "e": int((now or time.time()) + SESSION_SECONDS)}).encode())
    signature = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def read_session(secret: str, cookie: str | None, now: float | None = None) -> tuple[str, int] | None:
    """(member_id, session_version) from a valid, unexpired cookie; None otherwise."""
    try:
        payload, signature = (cookie or "").split(".")
        expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_unb64(payload))
        if data["e"] < (now or time.time()):
            return None
        return str(data["m"]), int(data["v"])
    except (ValueError, KeyError, TypeError):
        return None
