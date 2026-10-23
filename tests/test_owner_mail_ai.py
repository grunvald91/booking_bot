"""The mail AI call must not cut reasoning models off and must accept any model from the env."""
import asyncio
import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from web.api.routes import owner_mail


class FakeResponse:
    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def fake_client(sent, content):
    class Client:
        def __init__(self, timeout):
            sent["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers, json):
            sent["body"] = json
            return FakeResponse(content)

    return Client


def test_hub_uses_model_from_env_and_large_limits(monkeypatch):
    sent = {}
    monkeypatch.setenv("CLAUDEHUB_API_KEY", "test-key")
    monkeypatch.setenv("SERVGO_MAIL_AI_MODEL", "deepseek-v4.1-flash")
    monkeypatch.delenv("SERVGO_MAIL_AI_MAX_TOKENS", raising=False)
    monkeypatch.delenv("SERVGO_MAIL_AI_TIMEOUT", raising=False)
    monkeypatch.setattr(owner_mail.httpx, "AsyncClient", fake_client(sent, '{"subject":"a","body":"b"}'))
    result = asyncio.run(owner_mail.hub("prompt"))
    assert result == {"subject": "a", "body": "b"}
    assert sent["body"]["model"] == "deepseek-v4.1-flash"
    assert sent["body"]["max_completion_tokens"] == 32000
    assert sent["timeout"] == 300.0


def test_hub_reads_json_wrapped_in_code_fence(monkeypatch):
    sent = {}
    monkeypatch.setenv("CLAUDEHUB_API_KEY", "test-key")
    fenced = chr(96) * 3 + 'json\n{"critical": false, "reason": ""}\n' + chr(96) * 3
    monkeypatch.setattr(owner_mail.httpx, "AsyncClient", fake_client(sent, fenced))
    assert asyncio.run(owner_mail.hub("prompt")) == {"critical": False, "reason": ""}
