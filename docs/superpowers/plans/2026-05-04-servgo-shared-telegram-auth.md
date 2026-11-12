# Servgo Shared Telegram Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build symmetric Telegram Login Widget authentication for `gid.servgo.ru` and `servgo.ru` with a shared `.servgo.ru` session cookie.

**Architecture:** Add one small shared Python auth module and place the same file in both repositories. Each service verifies its own Telegram bot login payload, writes to the same shared auth database via `AUTH_DB_*`, and sets/reads the same `servgo_session` cookie. Product permissions stay inside each service: Sochi Guide uses identity for chat memory, booking uses identity for local `users` rows and role checks.

**Tech Stack:** Python 3, FastAPI in `sochi-concierge`, aiohttp in `booking_bot`, PostgreSQL via `psycopg2`, existing pytest/unittest tests, Telegram Login Widget HMAC.

---

## Repositories

- Booking repo: `C:\Users\User\booking_bot`
- Sochi Guide repo: `C:\Users\User\sochi-concierge`

The booking repo currently has unrelated dirty files in landing-page code. Do not edit or revert them while executing this plan.

## File Structure

Create or modify these files:

- Create `C:\Users\User\booking_bot\servgo_auth.py`: shared auth module.
- Create `C:\Users\User\booking_bot\tests\test_servgo_auth.py`: pure unit tests for Telegram HMAC and session helpers.
- Modify `C:\Users\User\booking_bot\requirements.txt`: add `psycopg2-binary`.
- Copy `C:\Users\User\booking_bot\servgo_auth.py` to `C:\Users\User\sochi-concierge\servgo_auth.py`.
- Create `C:\Users\User\sochi-concierge\tests\test_servgo_auth.py`: same pure tests run in the guide repo.
- Modify `C:\Users\User\sochi-concierge\requirements.txt`: add `psycopg2-binary`.
- Modify `C:\Users\User\sochi-concierge\auth.py`: delegate auth/session functions to `servgo_auth.py`, keep anonymous-data migration.
- Modify `C:\Users\User\sochi-concierge\web\api.py`: support `servgo_session` cookie in auth endpoints and user resolution.
- Create `C:\Users\User\sochi-concierge\tests\test_shared_cookie_auth.py`: API tests for cookie login/logout behavior.
- Modify `C:\Users\User\booking_bot\webapp\server.py`: add Telegram Login Widget endpoint, shared session validation, and shared logout handling.
- Create `C:\Users\User\booking_bot\tests\test_webapp_shared_auth.py`: unit tests for booking request identity helpers.
- Modify `C:\Users\User\booking_bot\webapp\templates\booking.html`: add Telegram Login Widget container for browser users.
- Modify `C:\Users\User\booking_bot\webapp\static\js\booking.js`: add web auth check, login callback, and credentialed requests.
- Create `C:\Users\User\booking_bot\tests\test_booking_shared_auth_frontend.py`: static tests for booking auth UI hooks.
- Modify `.env.example` in both repos: document shared auth variables.

---

### Task 1: Shared Auth Core in Booking Repo

**Files:**
- Create: `C:\Users\User\booking_bot\tests\test_servgo_auth.py`
- Create: `C:\Users\User\booking_bot\servgo_auth.py`
- Modify: `C:\Users\User\booking_bot\requirements.txt`

- [ ] **Step 1: Write failing tests for Telegram HMAC and session helpers**

Create `tests/test_servgo_auth.py`:

```python
import hashlib
import hmac
import time

import servgo_auth


def _signed_login_payload(bot_token: str, payload: dict) -> dict:
    data = {key: str(value) for key, value in payload.items()}
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    data["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return data


def test_telegram_login_accepts_valid_signed_payload():
    payload = _signed_login_payload(
        "123456:test",
        {
            "id": 777,
            "first_name": "Ivan",
            "username": "ivan",
            "auth_date": int(time.time()),
        },
    )

    assert servgo_auth.verify_telegram_login(payload, ["123456:test"]) is True


def test_telegram_login_rejects_tampered_payload():
    payload = _signed_login_payload(
        "123456:test",
        {
            "id": 777,
            "first_name": "Ivan",
            "auth_date": int(time.time()),
        },
    )
    payload["first_name"] = "Petr"

    assert servgo_auth.verify_telegram_login(payload, ["123456:test"]) is False


def test_telegram_login_rejects_stale_auth_date():
    payload = _signed_login_payload(
        "123456:test",
        {
            "id": 777,
            "first_name": "Ivan",
            "auth_date": int(time.time()) - 90000,
        },
    )

    assert servgo_auth.verify_telegram_login(payload, ["123456:test"]) is False


def test_session_tokens_are_hashed_before_storage():
    token = "abc123"

    assert servgo_auth.hash_session_token(token) == hashlib.sha256(token.encode()).hexdigest()
    assert servgo_auth.hash_session_token(token) != token


def test_cookie_options_are_shared_for_servgo_domain(monkeypatch):
    monkeypatch.setenv("AUTH_COOKIE_DOMAIN", ".servgo.ru")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")

    options = servgo_auth.auth_cookie_kwargs()

    assert options["domain"] == ".servgo.ru"
    assert options["httponly"] is True
    assert options["secure"] is True
    assert options["samesite"] == "Lax"
    assert options["path"] == "/"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_servgo_auth.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'servgo_auth'`.

- [ ] **Step 3: Add the shared auth module**

Create `servgo_auth.py`:

```python
"""Shared Telegram Login Widget and Servgo session helpers."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Callable, Iterable


AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "servgo_session")
SESSION_EXPIRE_DAYS = int(os.getenv("AUTH_SESSION_DAYS", "30"))
DEFAULT_MAX_AUTH_AGE_SECONDS = 24 * 60 * 60


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def auth_db_config() -> dict:
    return {
        "host": os.getenv("AUTH_DB_HOST", os.getenv("DB_HOST", "localhost")),
        "port": os.getenv("AUTH_DB_PORT", os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("AUTH_DB_NAME", os.getenv("DB_NAME", "servgo_auth")),
        "user": os.getenv("AUTH_DB_USER", os.getenv("DB_USER", "postgres")),
        "password": os.getenv("AUTH_DB_PASSWORD", os.getenv("DB_PASSWORD", "")),
    }


def _get_conn():
    import psycopg2

    conn = psycopg2.connect(**auth_db_config())
    conn.autocommit = True
    return conn


_INIT_SQL = """
CREATE TABLE IF NOT EXISTS web_users (
    id           SERIAL PRIMARY KEY,
    telegram_id  BIGINT UNIQUE NOT NULL,
    first_name   TEXT NOT NULL DEFAULT '',
    last_name    TEXT NOT NULL DEFAULT '',
    username     TEXT NOT NULL DEFAULT '',
    photo_url    TEXT NOT NULL DEFAULT '',
    auth_date    TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS web_sessions (
    token_hash    TEXT PRIMARY KEY,
    telegram_id   BIGINT NOT NULL REFERENCES web_users(telegram_id),
    anon_user_id  BIGINT,
    source_service TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at    TIMESTAMPTZ NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_web_sessions_telegram
    ON web_sessions(telegram_id);
"""

_MIGRATION_SQL = """
ALTER TABLE web_sessions ADD COLUMN IF NOT EXISTS token_hash TEXT;
ALTER TABLE web_sessions ADD COLUMN IF NOT EXISTS source_service TEXT NOT NULL DEFAULT '';
"""


def init_tables(conn_factory: Callable = _get_conn) -> None:
    conn = conn_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(_INIT_SQL)
            cur.execute(_MIGRATION_SQL)
    finally:
        conn.close()


def _data_check_string(data: dict) -> str:
    filtered = {
        key: str(value)
        for key, value in data.items()
        if key != "hash" and value is not None
    }
    return "\n".join(f"{key}={value}" for key, value in sorted(filtered.items()))


def verify_telegram_login(
    data: dict,
    bot_tokens: Iterable[str],
    *,
    now: float | None = None,
    max_age_seconds: int = DEFAULT_MAX_AUTH_AGE_SECONDS,
) -> bool:
    received_hash = str(data.get("hash", ""))
    if not received_hash:
        return False

    try:
        auth_date = int(data.get("auth_date", 0))
    except (TypeError, ValueError):
        return False

    current_time = time.time() if now is None else now
    if current_time - auth_date > max_age_seconds:
        return False
    if auth_date - current_time > 60:
        return False

    data_check_string = _data_check_string(data)
    for token in bot_tokens:
        if not token:
            continue
        secret_key = hashlib.sha256(token.encode()).digest()
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(calculated_hash, received_hash):
            return True
    return False


def auth_dict_from_payload(payload: dict) -> dict:
    auth_dict = {
        "id": str(payload.get("id", "")),
        "first_name": payload.get("first_name", "") or "",
        "auth_date": str(payload.get("auth_date", "")),
        "hash": payload.get("hash", "") or "",
    }
    for key in ("last_name", "username", "photo_url"):
        value = payload.get(key)
        if value:
            auth_dict[key] = value
    return auth_dict


def user_from_auth_dict(data: dict) -> dict:
    first_name = data.get("first_name", "") or ""
    last_name = data.get("last_name", "") or ""
    return {
        "telegram_id": int(data["id"]),
        "id": int(data["id"]),
        "first_name": first_name,
        "last_name": last_name,
        "username": data.get("username", "") or "",
        "photo_url": data.get("photo_url", "") or "",
        "full_name": f"{first_name} {last_name}".strip() or data.get("username", "") or f"User {data['id']}",
    }


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_or_update_user(data: dict, conn_factory: Callable = _get_conn) -> dict:
    from psycopg2.extras import RealDictCursor

    auth_date = datetime.fromtimestamp(int(data["auth_date"]), tz=timezone.utc)
    conn = conn_factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO web_users (telegram_id, first_name, last_name, username, photo_url, auth_date, last_login)
                VALUES (%(tid)s, %(fn)s, %(ln)s, %(un)s, %(ph)s, %(ad)s, NOW())
                ON CONFLICT (telegram_id) DO UPDATE SET
                    first_name = EXCLUDED.first_name,
                    last_name  = EXCLUDED.last_name,
                    username   = EXCLUDED.username,
                    photo_url  = EXCLUDED.photo_url,
                    auth_date  = EXCLUDED.auth_date,
                    last_login = NOW()
                RETURNING telegram_id, first_name, last_name, username, photo_url
                """,
                {
                    "tid": int(data["id"]),
                    "fn": data.get("first_name", "") or "",
                    "ln": data.get("last_name", "") or "",
                    "un": data.get("username", "") or "",
                    "ph": data.get("photo_url", "") or "",
                    "ad": auth_date,
                },
            )
            return dict(cur.fetchone())
    finally:
        conn.close()


def create_session(
    telegram_id: int,
    anon_user_id: int | None = None,
    *,
    source_service: str = "",
    conn_factory: Callable = _get_conn,
) -> str:
    token = secrets.token_hex(32)
    token_hash = hash_session_token(token)
    conn = conn_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO web_sessions (token_hash, telegram_id, anon_user_id, source_service, expires_at)
                VALUES (%s, %s, %s, %s, NOW() + (%s * INTERVAL '1 day'))
                """,
                (token_hash, telegram_id, anon_user_id, source_service, SESSION_EXPIRE_DAYS),
            )
        return token
    finally:
        conn.close()


def get_session(token: str | None, conn_factory: Callable = _get_conn) -> dict | None:
    if not token:
        return None
    from psycopg2.extras import RealDictCursor

    conn = conn_factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT s.telegram_id, u.first_name, u.last_name, u.username, u.photo_url
                FROM web_sessions s
                JOIN web_users u ON u.telegram_id = s.telegram_id
                WHERE s.token_hash = %s AND s.is_active = TRUE AND s.expires_at > NOW()
                """,
                (hash_session_token(token),),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def expire_session(token: str | None, conn_factory: Callable = _get_conn) -> None:
    if not token:
        return
    conn = conn_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE web_sessions SET is_active = FALSE WHERE token_hash = %s",
                (hash_session_token(token),),
            )
    finally:
        conn.close()


def auth_cookie_kwargs() -> dict:
    domain = os.getenv("AUTH_COOKIE_DOMAIN", ".servgo.ru")
    options = {
        "max_age": SESSION_EXPIRE_DAYS * 24 * 60 * 60,
        "httponly": True,
        "secure": _env_bool("AUTH_COOKIE_SECURE", False),
        "samesite": os.getenv("AUTH_COOKIE_SAMESITE", "Lax"),
        "path": "/",
    }
    if domain:
        options["domain"] = domain
    return options


def clear_cookie_kwargs() -> dict:
    domain = os.getenv("AUTH_COOKIE_DOMAIN", ".servgo.ru")
    options = {"path": "/"}
    if domain:
        options["domain"] = domain
    return options
```

- [ ] **Step 4: Add runtime dependency**

Append to `requirements.txt`:

```text

# Shared web authentication
psycopg2-binary>=2.9.9
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
pytest tests/test_servgo_auth.py -q
```

Expected: `5 passed`.

- [ ] **Step 6: Commit booking shared core**

Run:

```powershell
git add servgo_auth.py tests/test_servgo_auth.py requirements.txt
git commit -m "feat: add shared Servgo auth core"
```

---

### Task 2: Copy Shared Auth Core to Sochi Guide

**Files:**
- Create: `C:\Users\User\sochi-concierge\servgo_auth.py`
- Create: `C:\Users\User\sochi-concierge\tests\test_servgo_auth.py`
- Modify: `C:\Users\User\sochi-concierge\requirements.txt`

- [ ] **Step 1: Copy the shared module exactly**

Run:

```powershell
Copy-Item -LiteralPath C:\Users\User\booking_bot\servgo_auth.py -Destination C:\Users\User\sochi-concierge\servgo_auth.py
```

Expected: `C:\Users\User\sochi-concierge\servgo_auth.py` exists and matches the booking copy.

- [ ] **Step 2: Copy the pure shared-auth tests exactly**

Run:

```powershell
Copy-Item -LiteralPath C:\Users\User\booking_bot\tests\test_servgo_auth.py -Destination C:\Users\User\sochi-concierge\tests\test_servgo_auth.py
```

- [ ] **Step 3: Add runtime dependency**

Append to `C:\Users\User\sochi-concierge\requirements.txt`:

```text

# Shared web authentication
psycopg2-binary>=2.9.9
```

- [ ] **Step 4: Run Sochi shared auth tests**

Run:

```powershell
pytest tests/test_servgo_auth.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Commit Sochi shared core**

Run in `C:\Users\User\sochi-concierge`:

```powershell
git add servgo_auth.py tests/test_servgo_auth.py requirements.txt
git commit -m "feat: add shared Servgo auth core"
```

---

### Task 3: Sochi Guide Cookie Session API

**Files:**
- Modify: `C:\Users\User\sochi-concierge\auth.py`
- Modify: `C:\Users\User\sochi-concierge\web\api.py`
- Create: `C:\Users\User\sochi-concierge\tests\test_shared_cookie_auth.py`

- [ ] **Step 1: Write failing API tests for shared cookie auth**

Create `tests/test_shared_cookie_auth.py`:

```python
from fastapi.testclient import TestClient

import web.api as api


def test_auth_me_accepts_shared_cookie(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_session",
        lambda token: {
            "telegram_id": 777,
            "first_name": "Ivan",
            "last_name": "",
            "username": "ivan",
            "photo_url": "",
        } if token == "shared-token" else None,
    )

    response = TestClient(api.app).get(
        "/api/auth/me",
        cookies={api.AUTH_COOKIE_NAME: "shared-token"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["telegram_id"] == 777


def test_chat_uses_shared_cookie_identity(monkeypatch):
    monkeypatch.setattr(api, "_check_rate_limit", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        api,
        "get_session",
        lambda token: {"telegram_id": 777} if token == "shared-token" else None,
    )
    monkeypatch.setattr(api, "find_places_for_message", lambda _text, limit=4: [])
    monkeypatch.setattr(api, "_build_booking_chat_response", lambda _text, _places: None)

    calls = {}
    monkeypatch.setattr(api.ai, "ask", lambda user_id, text: calls.setdefault("user_id", user_id) or "ok")

    response = TestClient(api.app).post(
        "/api/chat",
        cookies={api.AUTH_COOKIE_NAME: "shared-token"},
        json={"message": "hello", "session_id": "browser-session"},
    )

    assert response.status_code == 200
    assert calls["user_id"] == 777


def test_logout_expires_cookie_session(monkeypatch):
    expired = []
    monkeypatch.setattr(api, "expire_session", lambda token: expired.append(token))

    response = TestClient(api.app).post(
        "/api/auth/logout",
        cookies={api.AUTH_COOKIE_NAME: "shared-token"},
    )

    assert response.status_code == 200
    assert expired == ["shared-token"]
    assert "servgo_session" in response.headers["set-cookie"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_shared_cookie_auth.py -q
```

Expected: FAIL because `api.AUTH_COOKIE_NAME` is not imported and `/api/auth/me` ignores cookies.

- [ ] **Step 3: Replace Sochi auth primitives with shared auth wrappers**

Modify `auth.py` so the top-level auth/session functions are imported from `servgo_auth`, while `verify_telegram_auth` keeps the existing public function name:

```python
"""Authentication helpers for Sochi Guide."""

import logging

from config import TELEGRAM_TOKEN
from servgo_auth import (
    AUTH_COOKIE_NAME,
    auth_cookie_kwargs,
    clear_cookie_kwargs,
    create_or_update_user,
    create_session,
    expire_session,
    get_session,
    init_tables,
    verify_telegram_login,
)

logger = logging.getLogger(__name__)


def verify_telegram_auth(data: dict) -> bool:
    """Verify Telegram Login Widget data for the Sochi Guide bot."""
    return verify_telegram_login(data, [TELEGRAM_TOKEN])
```

Keep the existing `migrate_anonymous_data()` function in the same file below this wrapper block. Do not delete or change its body.

- [ ] **Step 4: Update Sochi API imports and session resolution**

In `web/api.py`, change the FastAPI import:

```python
from fastapi import FastAPI, Request, Response
```

Change the auth import block to include cookie helpers:

```python
from auth import (
    AUTH_COOKIE_NAME,
    auth_cookie_kwargs,
    clear_cookie_kwargs,
    init_tables,
    verify_telegram_auth,
    create_or_update_user,
    create_session,
    get_session,
    expire_session,
    migrate_anonymous_data,
)
```

Add this helper above `_get_user_id`:

```python
def _session_from_request(request: Request) -> dict | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        session = get_session(auth_header[7:])
        if session:
            return session

    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        return get_session(cookie_token)

    return None
```

Replace `_get_user_id` with:

```python
def _get_user_id(request: Request, session_id: str = "") -> int:
    """Resolve user_id from shared auth session or fallback to anonymous."""
    session = _session_from_request(request)
    if session:
        return session["telegram_id"]
    return _anon_user_id(session_id or request.client.host)
```

- [ ] **Step 5: Update Sochi auth endpoints**

Change the `auth_telegram` signature and set the shared cookie:

```python
@app.post("/api/auth/telegram")
async def auth_telegram(data: TelegramAuthData, request: Request, response: Response):
    """Authenticate via Telegram Login Widget."""
    auth_dict = {
        "id": str(data.id),
        "first_name": data.first_name,
        "auth_date": str(data.auth_date),
        "hash": data.hash,
    }
    if data.last_name:
        auth_dict["last_name"] = data.last_name
    if data.username:
        auth_dict["username"] = data.username
    if data.photo_url:
        auth_dict["photo_url"] = data.photo_url

    if not verify_telegram_auth(auth_dict):
        return JSONResponse(status_code=401, content={"error": "Invalid auth data"})

    user = create_or_update_user(auth_dict)

    anon_id = None
    if data.session_id:
        anon_id = _anon_user_id(data.session_id)

    migrate_anonymous_data(anon_id, data.id)

    token = create_session(data.id, anon_id, source_service="guide")
    response.set_cookie(AUTH_COOKIE_NAME, token, **auth_cookie_kwargs())

    return {
        "token": token,
        "user": {
            "telegram_id": user["telegram_id"],
            "first_name": user["first_name"],
            "last_name": user.get("last_name", ""),
            "username": user.get("username", ""),
            "photo_url": user.get("photo_url", ""),
        },
    }
```

Replace `auth_me` with:

```python
@app.get("/api/auth/me")
async def auth_me(request: Request):
    """Get current user info from shared session."""
    session = _session_from_request(request)
    if not session:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    return {
        "user": {
            "telegram_id": session["telegram_id"],
            "first_name": session.get("first_name", ""),
            "last_name": session.get("last_name", ""),
            "username": session.get("username", ""),
            "photo_url": session.get("photo_url", ""),
        }
    }
```

Replace `auth_logout` with:

```python
@app.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response):
    """Invalidate shared session."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        expire_session(auth_header[7:])

    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        expire_session(cookie_token)

    response.delete_cookie(AUTH_COOKIE_NAME, **clear_cookie_kwargs())
    return {"ok": True}
```

Replace `_require_admin_session` with:

```python
def _require_admin_session(request: Request):
    session = _session_from_request(request)
    if not session:
        return None, JSONResponse(status_code=401, content={"error": "Not authenticated"})
    if session["telegram_id"] != OWNER_CHAT_ID:
        return None, JSONResponse(status_code=403, content={"error": "Admin only"})
    return session, None
```

Replace `history` with:

```python
@app.get("/api/history")
async def history(request: Request, limit: int = 50):
    """Get chat history for authenticated user."""
    session = _session_from_request(request)
    if not session:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    user_id = session["telegram_id"]
    limit = min(limit, 100)
    messages = get_chat_history(user_id, limit=limit)
    return {"messages": messages}
```

- [ ] **Step 6: Run Sochi API tests**

Run:

```powershell
pytest tests/test_shared_cookie_auth.py tests/test_web_api_reviews.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Sochi cookie support**

Run in `C:\Users\User\sochi-concierge`:

```powershell
git add auth.py web/api.py tests/test_shared_cookie_auth.py
git commit -m "feat: use shared Servgo auth cookie"
```

---

### Task 4: Booking Backend Shared Auth

**Files:**
- Modify: `C:\Users\User\booking_bot\webapp\server.py`
- Create: `C:\Users\User\booking_bot\tests\test_webapp_shared_auth.py`

- [ ] **Step 1: Write failing tests for booking shared identity helpers**

Create `tests/test_webapp_shared_auth.py`:

```python
import asyncio

from multidict import CIMultiDict

import webapp.server as server


class FakeRequest:
    def __init__(self, headers=None, cookies=None):
        self.headers = CIMultiDict(headers or {})
        self.cookies = cookies or {}


def test_shared_cookie_identity_is_used_when_init_data_missing(monkeypatch):
    monkeypatch.setattr(server, "validate_webapp_data", lambda _data: None)
    monkeypatch.setattr(
        server,
        "shared_get_session",
        lambda token: {
            "telegram_id": 777,
            "first_name": "Ivan",
            "last_name": "",
            "username": "ivan",
            "photo_url": "",
        } if token == "shared-token" else None,
    )

    user = asyncio.run(server.get_authenticated_telegram_user(FakeRequest(cookies={"servgo_session": "shared-token"})))

    assert user["id"] == 777
    assert user["username"] == "ivan"


def test_init_data_identity_has_priority_over_shared_cookie(monkeypatch):
    monkeypatch.setattr(server, "validate_webapp_data", lambda _data: {"id": 111, "first_name": "Telegram"})
    monkeypatch.setattr(server, "shared_get_session", lambda _token: {"telegram_id": 777})

    user = asyncio.run(
        server.get_authenticated_telegram_user(
            FakeRequest(
                headers={"X-Telegram-Init-Data": "signed"},
                cookies={"servgo_session": "shared-token"},
            )
        )
    )

    assert user["id"] == 111


def test_api_auth_me_accepts_shared_cookie(monkeypatch):
    monkeypatch.setattr(server, "validate_webapp_data", lambda _data: None)
    monkeypatch.setattr(
        server,
        "shared_get_session",
        lambda token: {
            "telegram_id": 777,
            "first_name": "Ivan",
            "last_name": "",
            "username": "ivan",
            "photo_url": "",
        } if token == "shared-token" else None,
    )

    response = asyncio.run(server.api_auth_me(FakeRequest(cookies={"servgo_session": "shared-token"})))

    assert response.status == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_webapp_shared_auth.py -q
```

Expected: FAIL because `get_authenticated_telegram_user`, `api_auth_me`, and `shared_get_session` do not exist.

- [ ] **Step 3: Import shared auth helpers in booking server**

In `webapp/server.py`, add imports near existing imports:

```python
from servgo_auth import (
    AUTH_COOKIE_NAME,
    auth_cookie_kwargs,
    auth_dict_from_payload,
    clear_cookie_kwargs,
    create_or_update_user as shared_create_or_update_user,
    create_session as shared_create_session,
    expire_session as shared_expire_session,
    get_session as shared_get_session,
    init_tables as init_shared_auth_tables,
    user_from_auth_dict,
    verify_telegram_login,
)
```

- [ ] **Step 4: Add booking identity helpers**

Add below `validate_webapp_data`:

```python
async def get_authenticated_telegram_user(request: web.Request) -> dict | None:
    """Return Telegram identity from WebApp initData or shared Servgo session."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = validate_webapp_data(init_data)
    if user:
        return user

    shared_token = request.cookies.get(AUTH_COOKIE_NAME)
    session = shared_get_session(shared_token)
    if not session:
        return None

    return {
        "id": session["telegram_id"],
        "first_name": session.get("first_name", "") or "",
        "last_name": session.get("last_name", "") or "",
        "username": session.get("username", "") or "",
        "photo_url": session.get("photo_url", "") or "",
    }


async def get_or_create_booking_user_from_auth(session, auth_user: dict):
    telegram_id = int(auth_user["id"])
    first_name = auth_user.get("first_name", "") or ""
    last_name = auth_user.get("last_name", "") or ""
    username = auth_user.get("username", "") or ""
    full_name = f"{first_name} {last_name}".strip() or username or f"User {telegram_id}"
    return await get_or_create_user(
        session,
        telegram_id=telegram_id,
        username=username,
        full_name=full_name,
    )
```

- [ ] **Step 5: Use shared identity in existing request auth**

In `get_user_from_request`, replace:

```python
init_data = request.headers.get('X-Telegram-Init-Data', '')
user = validate_webapp_data(init_data)
```

with:

```python
user = await get_authenticated_telegram_user(request)
```

Keep the existing `owner_session` fallback below it.

In `get_client_from_request`, replace:

```python
init_data = request.headers.get('X-Telegram-Init-Data', '')
user = validate_webapp_data(init_data)
```

with:

```python
user = await get_authenticated_telegram_user(request)
```

In client endpoints that directly call `validate_webapp_data`, replace the local two-line pattern with:

```python
user = await get_authenticated_telegram_user(request)
```

Apply this to:

- `api_client_last_bookings`
- `api_client_my_bookings`
- `api_client_cancel_booking`
- `api_client_reschedule_booking`
- `api_client_my_subscriptions`
- `api_client_buy_subscription`
- `api_client_prepayment_sent`
- `api_client_subscription_payment_sent`
- `api_client_subscription_upload_receipt`

In `api_client_create_booking`, replace the initial auth lookup with:

```python
user = await get_authenticated_telegram_user(request)
```

Then replace the local authenticated-user creation block with:

```python
if user:
    db_user = await get_or_create_booking_user_from_auth(session, user)
elif client_name:
    from sqlalchemy import select as sa_select
    from database.models import User as UserModel

    db_user = None
    if client_phone:
        clean_phone = client_phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        result = await session.execute(
            sa_select(UserModel).where(UserModel.phone == clean_phone)
        )
        db_user = result.scalar_one_or_none()

    if not db_user:
        db_user = UserModel(
            telegram_id=0,
            full_name=client_name,
            phone=client_phone if client_phone else None,
        )
        session.add(db_user)
        await session.flush()
else:
    return web.json_response({'error': 'Требуется авторизация через Telegram или указание имени клиента'}, status=401)
```

- [ ] **Step 6: Add booking Telegram Login Widget endpoint**

Add this handler near existing auth handlers:

```python
async def api_auth_telegram(request: web.Request) -> web.Response:
    """Authenticate browser users via Telegram Login Widget."""
    try:
        payload = await request.json()
        auth_dict = auth_dict_from_payload(payload)

        if not verify_telegram_login(auth_dict, [BOT_TOKEN]):
            return web.json_response({"error": "Invalid auth data"}, status=401)

        shared_user = shared_create_or_update_user(auth_dict)
        token = shared_create_session(int(auth_dict["id"]), source_service="booking")

        response = web.json_response({
            "success": True,
            "user": {
                "telegram_id": shared_user["telegram_id"],
                "first_name": shared_user.get("first_name", ""),
                "last_name": shared_user.get("last_name", ""),
                "username": shared_user.get("username", ""),
                "photo_url": shared_user.get("photo_url", ""),
            },
        })
        response.set_cookie(AUTH_COOKIE_NAME, token, **auth_cookie_kwargs())
        return response
    except Exception as e:
        logger.error(f"Error in api_auth_telegram: {e}")
        return web.json_response({"error": str(e)}, status=500)
```

Add this handler near `api_auth_telegram`:

```python
async def api_auth_me(request: web.Request) -> web.Response:
    """Return current shared web user."""
    user = await get_authenticated_telegram_user(request)
    if not user:
        return web.json_response({"error": "Not authenticated"}, status=401)

    return web.json_response({
        "user": {
            "telegram_id": user["id"],
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", ""),
            "username": user.get("username", ""),
            "photo_url": user.get("photo_url", ""),
        }
    })
```

Update `api_auth_logout`:

```python
async def api_auth_logout(request: web.Request) -> web.Response:
    """Logout from booking owner session and shared Servgo session."""
    shared_token = request.cookies.get(AUTH_COOKIE_NAME)
    if shared_token:
        shared_expire_session(shared_token)

    response = web.json_response({'success': True})
    response.del_cookie('owner_session')
    response.del_cookie(AUTH_COOKIE_NAME, **clear_cookie_kwargs())
    return response
```

Update `api_auth_check` to check shared session before returning 401:

```python
async def api_auth_check(request: web.Request) -> web.Response:
    """Check current owner or shared web session."""
    session_cookie = request.cookies.get('owner_session')
    if session_cookie:
        telegram_id = verify_session_cookie(session_cookie)
        if telegram_id:
            admin, business_id = await check_admin_access(telegram_id)
            if admin:
                return web.json_response({'authenticated': True, 'telegram_id': telegram_id, 'kind': 'owner'})

    shared = shared_get_session(request.cookies.get(AUTH_COOKIE_NAME))
    if shared:
        return web.json_response({
            'authenticated': True,
            'telegram_id': shared['telegram_id'],
            'kind': 'shared',
        })

    return web.json_response({'authenticated': False}, status=401)
```

Register the new route in `create_webapp()`:

```python
app.router.add_post('/api/auth/telegram', api_auth_telegram)
app.router.add_get('/api/auth/me', api_auth_me)
```

Place it next to the existing auth routes.

- [ ] **Step 7: Initialize shared auth tables on webapp startup**

At the beginning of `create_webapp()`, after `app = web.Application()`, add:

```python
    try:
        init_shared_auth_tables()
    except Exception as e:
        logger.error(f"Shared auth table initialization failed: {e}")
```

- [ ] **Step 8: Run booking backend tests**

Run:

```powershell
pytest tests/test_webapp_shared_auth.py tests/test_booking_safety.py -q
```

Expected: all selected tests pass.

- [ ] **Step 9: Commit booking backend shared auth**

Run in `C:\Users\User\booking_bot`:

```powershell
git add webapp/server.py tests/test_webapp_shared_auth.py
git commit -m "feat: accept shared Servgo auth in booking"
```

---

### Task 5: Booking Web Login UI

**Files:**
- Modify: `C:\Users\User\booking_bot\webapp\templates\booking.html`
- Modify: `C:\Users\User\booking_bot\webapp\static\js\booking.js`
- Create: `C:\Users\User\booking_bot\tests\test_booking_shared_auth_frontend.py`

- [ ] **Step 1: Write failing static tests for booking login UI**

Create `tests/test_booking_shared_auth_frontend.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_booking_page_has_web_auth_panel_and_login_widget_container():
    html = (ROOT / "webapp" / "templates" / "booking.html").read_text(encoding="utf-8")

    assert 'id="web-auth-panel"' in html
    assert 'id="telegram-login-widget"' in html


def test_booking_js_defines_telegram_login_callback_and_auth_check():
    js = (ROOT / "webapp" / "static" / "js" / "booking.js").read_text(encoding="utf-8")

    assert "window.onTelegramAuth" in js
    assert "checkWebAuth()" in js
    assert "/api/auth/telegram" in js
    assert "/api/auth/me" in js
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_booking_shared_auth_frontend.py -q
```

Expected: FAIL because the booking template and JS do not have these auth hooks.

- [ ] **Step 3: Add booking auth panel markup**

In `webapp/templates/booking.html`, add this block inside `<div id="app">` before the skeleton loader:

```html
        <div id="web-auth-panel" class="web-auth-panel hidden">
            <div class="web-auth-copy">
                <strong id="web-auth-title">Войти через Telegram</strong>
                <span id="web-auth-subtitle">Так вы сможете видеть свои записи и абонементы на сайте.</span>
            </div>
            <div id="telegram-login-widget"></div>
            <button id="web-auth-logout" class="secondary-btn hidden" onclick="logoutWebAuth()">Выйти</button>
        </div>
```

- [ ] **Step 4: Add booking web auth JavaScript**

In `webapp/static/js/booking.js`, add after the `state` object:

```javascript
let webAuthUser = null;
```

Change the `DOMContentLoaded` handler to call `checkWebAuth()` before loading businesses:

```javascript
document.addEventListener('DOMContentLoaded', async () => {
    if (tg) {
        tg.ready();
        tg.expand();
        applyTelegramTheme();
    }
    await checkWebAuth();
    loadBusinesses();
    initSwipeGestures();
});
```

Add these functions after the `DOMContentLoaded` handler:

```javascript
async function checkWebAuth() {
    if (tg?.initData) {
        hideWebAuthPanel();
        return;
    }

    try {
        const response = await fetch('/api/auth/me', { credentials: 'same-origin' });
        if (response.ok) {
            const data = await response.json();
            webAuthUser = data.user || null;
            updateWebAuthPanel();
            return;
        }
    } catch (e) {
        console.warn('Auth check failed', e);
    }

    webAuthUser = null;
    updateWebAuthPanel();
    loadTelegramLoginWidget();
}

function updateWebAuthPanel() {
    const panel = document.getElementById('web-auth-panel');
    const title = document.getElementById('web-auth-title');
    const subtitle = document.getElementById('web-auth-subtitle');
    const widget = document.getElementById('telegram-login-widget');
    const logout = document.getElementById('web-auth-logout');
    if (!panel) return;

    panel.classList.remove('hidden');
    if (webAuthUser) {
        const name = webAuthUser.first_name || webAuthUser.username || 'Telegram';
        title.textContent = `Вы вошли как ${name}`;
        subtitle.textContent = 'Ваши записи и абонементы доступны на этом устройстве.';
        if (widget) widget.classList.add('hidden');
        if (logout) logout.classList.remove('hidden');
    } else {
        title.textContent = 'Войти через Telegram';
        subtitle.textContent = 'Так вы сможете видеть свои записи и абонементы на сайте.';
        if (widget) widget.classList.remove('hidden');
        if (logout) logout.classList.add('hidden');
    }
}

function hideWebAuthPanel() {
    const panel = document.getElementById('web-auth-panel');
    if (panel) panel.classList.add('hidden');
}

function loadTelegramLoginWidget() {
    const container = document.getElementById('telegram-login-widget');
    if (!container || container.querySelector('script')) return;

    const script = document.createElement('script');
    script.src = 'https://telegram.org/js/telegram-widget.js?22';
    script.setAttribute('data-telegram-login', 'Sochiservice_bot');
    script.setAttribute('data-size', 'medium');
    script.setAttribute('data-onauth', 'onTelegramAuth(user)');
    script.setAttribute('data-request-access', 'write');
    script.async = true;
    container.appendChild(script);
}

window.onTelegramAuth = async function(user) {
    try {
        const response = await fetch('/api/auth/telegram', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(user),
        });
        if (!response.ok) {
            showError('Не удалось войти через Telegram');
            return;
        }
        const data = await response.json();
        webAuthUser = data.user || null;
        updateWebAuthPanel();
        await refreshAuthenticatedSections();
    } catch (e) {
        console.error('Telegram auth error', e);
        showError('Ошибка авторизации через Telegram');
    }
};

async function logoutWebAuth() {
    await fetch('/api/auth/logout', {
        method: 'POST',
        credentials: 'same-origin',
    }).catch(() => {});
    webAuthUser = null;
    const container = document.getElementById('telegram-login-widget');
    if (container) container.innerHTML = '';
    updateWebAuthPanel();
    loadTelegramLoginWidget();
}

async function refreshAuthenticatedSections() {
    if (state.currentStep === 'my-bookings') {
        await showMyBookings();
    } else if (state.currentStep === 'my-subscriptions') {
        await showMySubscriptions();
    }
}
```

In `apiCall`, add `credentials: 'same-origin'` to the fetch options:

```javascript
const response = await fetch(endpoint, { ...options, headers, credentials: 'same-origin' });
```

- [ ] **Step 5: Add minimal auth panel CSS**

If `booking.css` already has utility styles for panels, use those. Otherwise add this focused CSS to `webapp/static/css/booking.css`:

```css
.web-auth-panel {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin: 12px 16px;
    padding: 12px;
    border: 1px solid var(--tg-theme-hint-color, #d9d9d9);
    border-radius: 8px;
    background: var(--tg-theme-secondary-bg-color, #fff);
}

.web-auth-copy {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 2px;
    font-size: 13px;
}

.web-auth-copy span {
    color: var(--tg-theme-hint-color, #707579);
}
```

Add `webapp/static/css/booking.css` to the commit for this task.

- [ ] **Step 6: Run frontend static tests**

Run:

```powershell
pytest tests/test_booking_shared_auth_frontend.py -q
```

Expected: `2 passed`.

- [ ] **Step 7: Commit booking web login UI**

Run:

```powershell
git add webapp/templates/booking.html webapp/static/js/booking.js webapp/static/css/booking.css tests/test_booking_shared_auth_frontend.py
git commit -m "feat: add Telegram web login to booking page"
```

---

### Task 6: Environment Examples and Final Verification

**Files:**
- Modify: `C:\Users\User\booking_bot\.env.example`
- Modify: `C:\Users\User\sochi-concierge\.env.example`

- [ ] **Step 1: Document shared auth env in booking**

Append to `C:\Users\User\booking_bot\.env.example`:

```text

# Shared Servgo auth database used by servgo.ru and gid.servgo.ru
AUTH_DB_HOST=localhost
AUTH_DB_PORT=5432
AUTH_DB_NAME=servgo_auth
AUTH_DB_USER=postgres
AUTH_DB_PASSWORD=servgo_auth_example_password
AUTH_COOKIE_NAME=servgo_session
AUTH_COOKIE_DOMAIN=.servgo.ru
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=Lax
AUTH_SESSION_DAYS=30
```

- [ ] **Step 2: Document shared auth env in Sochi Guide**

Append to `C:\Users\User\sochi-concierge\.env.example`:

```text

# Shared Servgo auth database used by servgo.ru and gid.servgo.ru
AUTH_DB_HOST=localhost
AUTH_DB_PORT=5432
AUTH_DB_NAME=servgo_auth
AUTH_DB_USER=postgres
AUTH_DB_PASSWORD=servgo_auth_example_password
AUTH_COOKIE_NAME=servgo_session
AUTH_COOKIE_DOMAIN=.servgo.ru
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=Lax
AUTH_SESSION_DAYS=30
```

- [ ] **Step 3: Run booking tests**

Run in `C:\Users\User\booking_bot`:

```powershell
pytest tests/test_servgo_auth.py tests/test_webapp_shared_auth.py tests/test_booking_shared_auth_frontend.py tests/test_booking_safety.py -q
```

Expected: all selected tests pass.

- [ ] **Step 4: Run Sochi Guide tests**

Run in `C:\Users\User\sochi-concierge`:

```powershell
pytest tests/test_servgo_auth.py tests/test_shared_cookie_auth.py tests/test_web_api_reviews.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit env docs**

Run in `C:\Users\User\booking_bot`:

```powershell
git add .env.example
git commit -m "docs: document shared auth settings"
```

Run in `C:\Users\User\sochi-concierge`:

```powershell
git add .env.example
git commit -m "docs: document shared auth settings"
```

- [ ] **Step 6: Production smoke test checklist**

After deployment, verify in a real browser:

```text
1. Open https://gid.servgo.ru/chat.
2. Log in via Telegram Login Widget.
3. Confirm browser has servgo_session cookie scoped to .servgo.ru.
4. Open https://servgo.ru/book.
5. Confirm booking page shows authenticated Telegram user without another Telegram approval.
6. Click logout on booking.
7. Refresh https://gid.servgo.ru/chat and confirm it is logged out.
8. Log in first on https://servgo.ru/book.
9. Open https://gid.servgo.ru/chat and confirm it is authenticated.
10. Open booking inside Telegram and confirm Telegram WebApp initData still works.
```
