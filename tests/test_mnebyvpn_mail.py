"""MNEBYVPN mail gateway accepts only a signed, one-time OTP dispatch request."""
import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from database.models import Base
from web.api.database import get_db
from web.api.routes import mnebyvpn_mail as relay


class MailRelayTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.backup = {k: os.environ.get(k) for k in (
            "MNEBYVPN_MAIL_GATEWAY_SECRET", "SMTP_HOST", "SMTP_FROM_EMAIL")}
        os.environ.update(MNEBYVPN_MAIL_GATEWAY_SECRET="s" * 48, SMTP_HOST="127.0.0.1",
                          SMTP_FROM_EMAIL="no-reply@servgo.ru")
        self.sent = []

        async def fake_send_email(**payload):
            self.sent.append(payload)
            return True

        self.real_send = relay.send_email
        relay.send_email = fake_send_email
        app = FastAPI()

        async def db_session():
            async with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = db_session
        app.include_router(relay.router, prefix="/api/auth")
        self.client = TestClient(app)

    async def asyncTearDown(self):
        relay.send_email = self.real_send
        self.client.close()
        for name, before in self.backup.items():
            if before is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = before
        await self.engine.dispose()

    def sign(self, body, nonce="n" * 32, timestamp=None, mutate=False):
        raw = json.dumps(body, separators=(",", ":")).encode()
        ts = str(timestamp if timestamp is not None else int(time.time()))
        sig = hmac.new(b"s" * 48, ts.encode() + b"." + nonce.encode() + b"." + raw,
                       hashlib.sha256).hexdigest()
        if mutate:
            sig = "0" * 64
        return raw, {"Content-Type": "application/json",
                     "X-Mnebyvpn-Timestamp": ts, "X-Mnebyvpn-Nonce": nonce,
                     "X-Mnebyvpn-Signature": sig}

    async def test_valid_sender_and_replay_refusal(self):
        raw, headers = self.sign({"email": "test@example.org", "code": "123456"})
        url = "/api/auth/mnebyvpn/email-code"
        first = self.client.post(url, content=raw, headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), {"sent": True})
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["from_override"], "mnebyvpn@servgo.ru")
        self.assertIn("123456", self.sent[0]["text_body"])
        self.assertEqual(self.client.post(url, content=raw, headers=headers).status_code, 409)
        self.assertEqual(len(self.sent), 1)

    async def test_nonce_cleanup_failure_does_not_block_otp_delivery(self):
        raw, headers = self.sign(
            {"email": "test@example.org", "code": "543210"}, nonce="b" * 32
        )
        with patch.object(relay, "delete", side_effect=RuntimeError("cleanup down")):
            result = self.client.post(
                "/api/auth/mnebyvpn/email-code", content=raw, headers=headers
            )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["from_override"], "mnebyvpn@servgo.ru")

    async def test_wrong_signature_expired_and_invalid_payload(self):
        url = "/api/auth/mnebyvpn/email-code"
        raw, h = self.sign({"email": "a@example.com", "code": "000001"}, mutate=True)
        self.assertEqual(self.client.post(url, content=raw, headers=h).status_code, 401)
        raw, h = self.sign({"email": "a@example.com", "code": "000001"},
                           nonce="q" * 32, timestamp=int(time.time())-600)
        self.assertEqual(self.client.post(url, content=raw, headers=h).status_code, 401)
        raw, h = self.sign({"email": "a@example.com", "code": "oops"}, nonce="z"*32)
        self.assertEqual(self.client.post(url, content=raw, headers=h).status_code, 400)
        self.assertEqual(self.sent, [])
