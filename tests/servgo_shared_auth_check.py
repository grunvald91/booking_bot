from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.api.main import app
from web.api.routes import auth


def _fake_token_out():
    return auth.TokenOut(
        token="local-jwt",
        role="client",
        user=auth.UserOut(
            id=123,
            full_name="SSO User",
            phone=None,
            username="sso_user",
        ),
    )


async def _fake_get_db():
    yield object()


def _current_frontend_bundle_text():
    index = (ROOT / "web" / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")
    marker = 'src="/assets/'
    start = index.index(marker) + len(marker)
    end = index.index('"', start)
    return (ROOT / "web" / "frontend" / "dist" / "assets" / index[start:end]).read_text(encoding="utf-8")


def test_frontend_exposes_three_auth_options_and_keeps_webapp_auto_login():
    index = (ROOT / "web" / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")
    text = (ROOT / "web" / "frontend" / "dist" / "servgo-shared-auth.js").read_text(encoding="utf-8")
    bundle = _current_frontend_bundle_text()

    assert "/servgo-shared-auth.js" in index
    assert '<script src="https://tg.servgo.ru/js/telegram-web-app.js" async></script>' in index
    assert "https://telegram.org/js/telegram-web-app.js" not in index
    assert "https://t.me/Sochiservice_bot?start=login" in bundle
    assert "Получить код" in bundle
    assert 'script.src = "https://tg.servgo.ru/widget.js"' in text
    assert 'script.setAttribute("data-onauth", "onServgoTelegramAuth(user)")' in text
    assert "Telegram Login Widget" in text
    assert "Официальный вход через Telegram без перехода в бота" in text
    assert "прокси" not in text
    assert "Перейти в бота" in text
    assert "Откроет @Sochiservice_bot" in text
    assert "Вход по коду" in text
    assert "одноразовый код" in text
    assert "function hasRenderedWidget" in text
    assert 'host.querySelector("iframe, button, a")' in text
    assert "Виджет еще загружается" not in text
    assert "Виджет не появился" not in text
    assert "Telegram Login Widget did not render in 10s" in text
    assert "async function exchangeTelegramWebApp" in text
    assert "function redirectAuthenticatedLogin" in text
    assert 'fetch("/api/auth/telegram"' in text
    assert "body: JSON.stringify({ init_data: initData })" in text
    assert "neutralizeNativeTelegramButton" not in text
    assert 'nativeButton.style.display = "none"' not in text


def test_shared_cookie_exchanges_for_local_jwt():
    async def fake_token_for_telegram_user(db, telegram_id, first_name=None, last_name=None, username=None):
        assert telegram_id == 77
        assert first_name == "Shared"
        return _fake_token_out()

    original_get_session = getattr(auth, "shared_get_session", None)
    original_cookie_name = getattr(auth, "auth_cookie_name", None)
    original_token_for_telegram_user = getattr(auth, "_token_for_telegram_user", None)
    auth.shared_get_session = lambda token: {
        "telegram_id": 77,
        "first_name": "Shared",
        "last_name": "User",
        "username": "shared_user",
        "photo_url": "",
    } if token == "shared-session" else None
    auth.auth_cookie_name = lambda: "servgo_session"
    auth._token_for_telegram_user = fake_token_for_telegram_user
    app.dependency_overrides[auth.get_db] = _fake_get_db
    try:
        client = TestClient(app)
        response = client.get("/auth/session", cookies={"servgo_session": "shared-session"})
    finally:
        if original_get_session is None:
            delattr(auth, "shared_get_session")
        else:
            auth.shared_get_session = original_get_session
        if original_cookie_name is None:
            delattr(auth, "auth_cookie_name")
        else:
            auth.auth_cookie_name = original_cookie_name
        if original_token_for_telegram_user is None:
            delattr(auth, "_token_for_telegram_user")
        else:
            auth._token_for_telegram_user = original_token_for_telegram_user
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["token"] == "local-jwt"
    assert response.json()["user"]["full_name"] == "SSO User"


def test_telegram_login_widget_issues_shared_cookie():
    async def fake_token_for_telegram_user(db, telegram_id, first_name=None, last_name=None, username=None):
        assert telegram_id == 77
        return _fake_token_out()

    calls = {}
    original_verify = getattr(auth, "verify_telegram_login", None)
    original_auth_dict_from_payload = getattr(auth, "auth_dict_from_payload", None)
    original_shared_create_or_update_user = getattr(auth, "shared_create_or_update_user", None)
    original_shared_create_session = getattr(auth, "shared_create_session", None)
    original_cookie_name = getattr(auth, "auth_cookie_name", None)
    original_cookie_kwargs = getattr(auth, "auth_cookie_kwargs", None)
    original_token_for_telegram_user = getattr(auth, "_token_for_telegram_user", None)
    auth.verify_telegram_login = lambda payload, tokens: True
    auth.auth_dict_from_payload = lambda payload: {
        "id": str(payload["id"]),
        "first_name": payload.get("first_name", ""),
        "last_name": payload.get("last_name", ""),
        "username": payload.get("username", ""),
        "photo_url": payload.get("photo_url", ""),
        "auth_date": str(payload["auth_date"]),
        "hash": payload["hash"],
    }
    auth.shared_create_or_update_user = lambda auth_dict: calls.setdefault("user", auth_dict)
    auth.shared_create_session = lambda telegram_id, source_service="": calls.setdefault(
        "session",
        f"{telegram_id}:{source_service}",
    ) and "shared-cookie"
    auth.auth_cookie_name = lambda: "servgo_session"
    auth.auth_cookie_kwargs = lambda: {"path": "/", "httponly": True, "samesite": "Lax"}
    auth._token_for_telegram_user = fake_token_for_telegram_user
    app.dependency_overrides[auth.get_db] = _fake_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/auth/telegram-login",
            json={
                "id": 77,
                "first_name": "Shared",
                "last_name": "User",
                "username": "shared_user",
                "photo_url": "",
                "auth_date": 1713700000,
                "hash": "valid",
            },
        )
    finally:
        for name, original in [
            ("verify_telegram_login", original_verify),
            ("auth_dict_from_payload", original_auth_dict_from_payload),
            ("shared_create_or_update_user", original_shared_create_or_update_user),
            ("shared_create_session", original_shared_create_session),
            ("auth_cookie_name", original_cookie_name),
            ("auth_cookie_kwargs", original_cookie_kwargs),
            ("_token_for_telegram_user", original_token_for_telegram_user),
        ]:
            if original is None:
                delattr(auth, name)
            else:
                setattr(auth, name, original)
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["token"] == "local-jwt"
    assert "servgo_session=shared-cookie" in response.headers["set-cookie"]


def test_telegram_webapp_init_data_issues_shared_cookie():
    async def fake_token_for_telegram_user(db, telegram_id, first_name=None, last_name=None, username=None):
        assert telegram_id == 77
        assert first_name == "Shared"
        return _fake_token_out()

    calls = {}
    original_validate_init_data = getattr(auth, "_validate_init_data", None)
    original_shared_auth_from_init_data = getattr(auth, "_shared_auth_from_init_data", None)
    original_set_shared_auth_cookie = getattr(auth, "_set_shared_auth_cookie", None)
    original_token_for_telegram_user = getattr(auth, "_token_for_telegram_user", None)
    auth._validate_init_data = lambda init_data: {
        "id": 77,
        "first_name": "Shared",
        "last_name": "User",
        "username": "shared_user",
    } if init_data == "valid-init-data" else None
    auth._shared_auth_from_init_data = lambda init_data, tg_user: calls.setdefault(
        "shared_auth",
        {
            "id": str(tg_user["id"]),
            "first_name": tg_user.get("first_name", ""),
            "last_name": tg_user.get("last_name", ""),
            "username": tg_user.get("username", ""),
            "photo_url": "",
            "auth_date": "1713700000",
            "hash": "valid",
        },
    )

    async def fake_set_shared_auth_cookie(response, auth_dict):
        calls["cookie"] = auth_dict
        response.set_cookie("servgo_session", "shared-webapp-cookie", path="/")

    auth._set_shared_auth_cookie = fake_set_shared_auth_cookie
    auth._token_for_telegram_user = fake_token_for_telegram_user
    app.dependency_overrides[auth.get_db] = _fake_get_db
    try:
        client = TestClient(app)
        response = client.post("/auth/telegram", json={"init_data": "valid-init-data"})
    finally:
        for name, original in [
            ("_validate_init_data", original_validate_init_data),
            ("_shared_auth_from_init_data", original_shared_auth_from_init_data),
            ("_set_shared_auth_cookie", original_set_shared_auth_cookie),
            ("_token_for_telegram_user", original_token_for_telegram_user),
        ]:
            if original is None:
                delattr(auth, name)
            else:
                setattr(auth, name, original)
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["token"] == "local-jwt"
    assert calls["shared_auth"]["id"] == "77"
    assert calls["cookie"]["id"] == "77"
    assert "servgo_session=shared-webapp-cookie" in response.headers["set-cookie"]


if __name__ == "__main__":
    test_frontend_exposes_three_auth_options_and_keeps_webapp_auto_login()
    test_shared_cookie_exchanges_for_local_jwt()
    test_telegram_login_widget_issues_shared_cookie()
    test_telegram_webapp_init_data_issues_shared_cookie()
