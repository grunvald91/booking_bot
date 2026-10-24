"""Signed in through Yandex (no Telegram), then signed in through Telegram: the accounts join automatically."""
import os
os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import time
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database.models import Base, Business, EmailIdentity, User, UserAccountMerge, YandexIdentity
from web.api import deps
from web.api.database import get_db
from web.api.routes import auth

WIDGET = {"id": 777, "first_name": "Иван", "auth_date": 1, "hash": "h"}


class YandexTelegramJoinTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async def no_cookie(response, auth_dict):
            return None

        self._originals = (auth.verify_telegram_login, auth._set_shared_auth_cookie)
        auth.verify_telegram_login = lambda payload, tokens: True
        auth._set_shared_auth_cookie = no_cookie
        app = FastAPI()
        app.include_router(auth.router, prefix="/auth")

        async def session():
            async with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = session
        self.client = TestClient(app)

    async def asyncTearDown(self):
        auth.verify_telegram_login, auth._set_shared_auth_cookie = self._originals
        auth._pending_codes.clear()
        self.client.close()
        await self.engine.dispose()

    async def yandex_user(self, *, email_password=False, phone="+79180001122"):
        async with self.sessions() as db:
            user = User(telegram_id=-123456, full_name="Иван Яндекс", email="ivan@yandex.ru", phone=phone, birthday="1990-05-17")
            db.add(user)
            await db.flush()
            db.add(YandexIdentity(yandex_id="1000", user_id=user.id, login="ivan"))
            db.add(Business(owner_id=user.id, name="Студия", business_type="beauty"))
            if email_password:
                db.add(EmailIdentity(user_id=user.id, email="ivan@yandex.ru", password_hash="x"))
            await db.commit()
            return user.id

    def bearer(self, user_id):
        return {"Authorization": "Bearer " + deps.create_token(user_id)}

    async def row(self, model, key):
        async with self.sessions() as db:
            return await db.get(model, key)

    async def test_telegram_login_while_signed_in_via_yandex_joins_the_accounts(self):
        yandex = await self.yandex_user()
        result = self.client.post("/auth/telegram-login", json=WIDGET, headers=self.bearer(yandex)).json()
        async with self.sessions() as db:
            telegram = await db.scalar(select(User).where(User.telegram_id == 777))
            identity = await db.get(YandexIdentity, "1000")
            owner = await db.scalar(select(Business.owner_id))
        self.assertEqual((result["user"]["id"], result["role"]), (telegram.id, "admin"))
        self.assertEqual((identity.user_id, owner), (telegram.id, telegram.id))
        self.assertEqual((telegram.phone, telegram.email, telegram.birthday), ("+79180001122", "ivan@yandex.ru", "1990-05-17"))
        self.assertEqual((await self.row(UserAccountMerge, yandex)).target_user_id, telegram.id)
        # the old Yandex session now opens the joined account
        me = self.client.get("/auth/me", headers=self.bearer(yandex)).json()
        self.assertEqual(me["id"], telegram.id)

    async def test_existing_telegram_account_also_joins(self):
        yandex = await self.yandex_user()
        async with self.sessions() as db:
            existing = User(telegram_id=777, full_name="Иван", phone="+70000000000")
            db.add(existing)
            await db.commit()
        result = self.client.post("/auth/telegram-login", json=WIDGET, headers=self.bearer(yandex)).json()
        self.assertEqual(result["user"]["id"], existing.id)
        self.assertEqual((await self.row(YandexIdentity, "1000")).user_id, existing.id)
        self.assertEqual((await self.row(User, existing.id)).phone, "+70000000000")  # own number is kept

    async def test_without_a_yandex_session_nothing_is_joined(self):
        yandex = await self.yandex_user()
        result = self.client.post("/auth/telegram-login", json=WIDGET).json()
        self.assertNotEqual(result["user"]["id"], yandex)
        self.assertEqual((await self.row(YandexIdentity, "1000")).user_id, yandex)
        self.assertIsNone(await self.row(UserAccountMerge, yandex))

    async def test_yandex_account_with_email_password_is_left_alone(self):
        yandex = await self.yandex_user(email_password=True)
        result = self.client.post("/auth/telegram-login", json=WIDGET, headers=self.bearer(yandex))
        self.assertEqual(result.status_code, 200)
        self.assertEqual((await self.row(YandexIdentity, "1000")).user_id, yandex)

    async def test_telegram_account_with_another_yandex_still_signs_in_without_joining(self):
        yandex = await self.yandex_user()
        async with self.sessions() as db:
            existing = User(telegram_id=777, full_name="Иван")
            db.add(existing)
            await db.flush()
            db.add(YandexIdentity(yandex_id="2000", user_id=existing.id, login="other"))
            await db.commit()
        result = self.client.post("/auth/telegram-login", json=WIDGET, headers=self.bearer(yandex))
        self.assertEqual((result.status_code, result.json()["user"]["id"]), (200, existing.id))
        self.assertEqual((await self.row(YandexIdentity, "1000")).user_id, yandex)
        self.assertIsNone(await self.row(UserAccountMerge, yandex))

    async def test_a_plain_telegram_session_is_not_joined_into_another_telegram(self):
        async with self.sessions() as db:
            first = User(telegram_id=555, full_name="Первый")
            db.add(first)
            await db.commit()
        result = self.client.post("/auth/telegram-login", json=WIDGET, headers=self.bearer(first.id)).json()
        self.assertNotEqual(result["user"]["id"], first.id)
        self.assertIsNone(await self.row(UserAccountMerge, first.id))

    async def test_phone_code_from_telegram_while_signed_in_via_yandex_joins_too(self):
        yandex = await self.yandex_user(phone=None)
        async with self.sessions() as db:
            telegram = User(telegram_id=777, full_name="Иван", phone="+79990001122")
            db.add(telegram)
            await db.commit()
        auth._pending_codes["+79990001122"] = ("123456", time.time())
        result = self.client.post("/auth/verify", json={"phone": "+79990001122", "code": "123456"},
                                  headers=self.bearer(yandex)).json()
        self.assertEqual(result["user"]["id"], telegram.id)
        self.assertEqual((await self.row(YandexIdentity, "1000")).user_id, telegram.id)


if __name__ == "__main__":
    unittest.main()
