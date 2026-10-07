"""Synthetic email and payment workflows; never send real email or access live data."""
import asyncio
import os
import re
import unittest
import uuid
from datetime import datetime, timedelta, time
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from sqlalchemy import select, func, text

import test_sales_agent as sales_fixture
from database.models import User, Booking, EmailIdentity, EmailChallenge, BookingReceipt, PrepaymentReview
from database.prepayment import expire_due_prepayments, payment_deadline
from web.api import deps
from web.api.routes import email_auth, payments, admin

PASSWORD = "Synthetic-password-123"
PNG = b"\x89PNG\r\n\x1a\nsynthetic-proof"


class EmailAndPaymentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.auth_patches = [patch.dict(os.environ, {"SMTP_HOST": "smtp.test.invalid", "SMTP_FROM_EMAIL": "no-reply@example.test",
            "SERVGO_EMAIL_AUTH_SECRET": "test-only-email-secret-32-characters"}),
            patch.object(deps, "SECRET_KEY", "test-only-jwt-secret-32-characters")]
        for item in self.auth_patches: item.start()
        await sales_fixture.SalesApiTests.asyncSetUp(self)
        self.app.include_router(email_auth.router, prefix="/auth")
        self.app.include_router(admin.router, prefix="/admin")
        self.app.include_router(payments.router, prefix="/admin")
        self.mail = AsyncMock(return_value=True)
        self.notice = AsyncMock()
        self.delivery_patches = [patch.object(email_auth, "send_email", self.mail),
            patch("bot.services.notification_events.dispatch_booking_event", self.notice),
            patch("bot.services.email_notifications.send_booking_email", AsyncMock())]
        for item in self.delivery_patches: item.start()

    async def asyncTearDown(self):
        for item in self.delivery_patches: item.stop()
        await sales_fixture.SalesApiTests.asyncTearDown(self)
        for item in reversed(self.auth_patches): item.stop()

    async def begin(self, email="owner@example.test", purpose="register", headers=None, password=PASSWORD):
        result = await self.client.post("/auth/email/start", headers=headers or {},
            json={"email": email, "password": password, "purpose": purpose, "full_name": "Демо пользователь"})
        self.assertEqual(result.status_code, 200, result.text)
        code = re.search(r"Код: (\d{6})", self.mail.call_args.kwargs["text_body"]).group(1)
        return result.json()["challenge_id"], code

    async def verify(self, challenge, code, headers=None):
        return await self.client.post("/auth/email/verify", headers=headers or {}, json={"challenge_id": challenge, "code": code})

    async def register(self, email="owner@example.test"):
        challenge, code = await self.begin(email)
        result = await self.verify(challenge, code)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    async def booking(self, *, at=11, rental=False, receipt=False, status="pending_prepayment", amount=1000):
        from database.models import Business
        async with self.sessions() as db:
            business = await db.get(Business, self.business)
            business.require_receipt_for_prepayment = receipt
            row = Booking(business_id=self.business, service_id=self.service, employee_id=self.employee, client_id=self.customer,
                booking_date=self.day, booking_time=time(at), prepayment_amount=amount, status=status,
                prepayment_requested_at=datetime.utcnow(), duration_minutes=120 if rental else None,
                resource_duration_minutes=120 if rental else 60, estimated_price=5000 if rental else None,
                notify_token=uuid.uuid4().hex)
            db.add(row); await db.commit()
            return row.id, row.notify_token

    async def submit(self, token, content=PNG):
        return await self.client.post(f"/bookings/by-token/{token}/receipt", files={"file": ("proof.png", content, "image/png")})

    async def details(self, bid, headers=None):
        result = await self.client.get(f"/admin/bookings/{bid}/payment-details", headers=headers or self.owner_auth)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    async def decide(self, bid, decision, version, headers=None):
        return await self.client.post(f"/admin/bookings/{bid}/prepayment-review", headers=headers or self.owner_auth,
            json={"decision": decision, "expected_version": version})

    async def test_register_without_telegram_and_login_requires_verified_email(self):
        challenge, code = await self.begin(" New@Example.Test ")
        login = await self.client.post("/auth/email/login", json={"email": "new@example.test", "password": PASSWORD})
        self.assertEqual(login.status_code, 401)
        result = await self.verify(challenge, code)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["role"], "client")
        async with self.sessions() as db:
            user = await db.get(User, result.json()["user"]["id"])
            self.assertLess(user.telegram_id, 0)
            self.assertIsNone(user.phone)
            identity = await db.get(EmailIdentity, "new@example.test")
            self.assertNotIn(PASSWORD, identity.password_hash)
        self.assertEqual((await self.verify(challenge, code)).status_code, 400)
        login = await self.client.post("/auth/email/login", json={"email": "new@example.test", "password": PASSWORD})
        self.assertEqual(login.status_code, 200)

    async def test_contact_email_never_claims_existing_owner_account(self):
        async with self.sessions() as db:
            (await db.get(User, self.owner)).email = "owner@example.test"
            await db.commit()
        result = await self.register()
        self.assertNotEqual(result["user"]["id"], self.owner)
        self.assertEqual(result["role"], "client")

    async def test_authenticated_link_preserves_business_and_requires_same_user(self):
        challenge, code = await self.begin(purpose="link", headers=self.owner_auth)
        self.assertEqual((await self.verify(challenge, code, self.outsider_auth)).status_code, 403)
        self.assertEqual((await self.verify(challenge, code)).status_code, 403)
        result = await self.verify(challenge, code, self.owner_auth)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["user"]["id"], self.owner)
        self.assertEqual(result.json()["role"], "admin")
        jwt_headers = {"Authorization": "Bearer " + result.json()["token"]}
        self.assertEqual((await self.client.get(f"/admin/prepayments?business_id={self.business}", headers=jwt_headers)).status_code, 200)

    async def test_email_owner_grant_works_without_starting_bot(self):
        result = await self.register()
        granted = await self.client.post(f"/admin/businesses/{self.business}/owners", headers=self.owner_auth, json={"email": "owner@example.test"})
        self.assertEqual(granted.status_code, 200, granted.text)
        async with self.sessions() as db:
            from database.crud import get_business_owners
            self.assertEqual({u.id for u in await get_business_owners(db, self.business)}, {self.owner, result["user"]["id"]})
        login = await self.client.post("/auth/email/login", json={"email": "owner@example.test", "password": PASSWORD})
        self.assertEqual(login.json()["role"], "admin")
        self.assertEqual(login.json()["user"]["id"], result["user"]["id"])
        not_verified = await self.client.post(f"/admin/businesses/{self.business}/owners", headers=self.owner_auth, json={"email": "unknown@example.test"})
        self.assertEqual(not_verified.status_code, 404)

    async def test_reset_invalidates_old_email_sessions_and_all_other_codes(self):
        original = await self.register()
        new_password = "Another-synthetic-password"
        older, _ = await self.begin(purpose="reset", password=new_password)
        challenge, code = await self.begin(purpose="reset", password=new_password)
        reset = await self.verify(challenge, code)
        self.assertEqual(reset.status_code, 200, reset.text)
        old_headers = {"Authorization": "Bearer " + original["token"]}
        self.assertEqual((await self.client.get("/auth/email/account", headers=old_headers)).status_code, 401)
        self.assertEqual((await self.verify(older, code)).status_code, 400)
        self.assertEqual((await self.client.post("/auth/email/login", json={"email": "owner@example.test", "password": PASSWORD})).status_code, 401)
        self.assertEqual((await self.client.post("/auth/email/login", json={"email": "owner@example.test", "password": new_password})).status_code, 200)

    async def test_expired_codes_and_five_wrong_attempts_fail(self):
        challenge, correct = await self.begin()
        wrong = "000000" if correct != "000000" else "111111"
        for _ in range(5): self.assertEqual((await self.verify(challenge, wrong)).status_code, 400)
        self.assertEqual((await self.verify(challenge, correct)).status_code, 400)
        challenge, correct = await self.begin("other@example.test")
        async with self.sessions() as db:
            (await db.get(EmailChallenge, challenge)).expires_at = datetime.utcnow() - timedelta(seconds=1)
            await db.commit()
        self.assertEqual((await self.verify(challenge, correct)).status_code, 400)

    async def test_send_and_login_rate_limits_persist_between_requests(self):
        for _ in range(5): await self.begin()
        limited = await self.client.post("/auth/email/start", json={"email": "owner@example.test", "purpose": "register", "password": PASSWORD, "full_name": "Demo"})
        self.assertEqual(limited.status_code, 429)
        for _ in range(10):
            self.assertEqual((await self.client.post("/auth/email/login", json={"email": "missing@example.test", "password": PASSWORD})).status_code, 401)
        self.assertEqual((await self.client.post("/auth/email/login", json={"email": "missing@example.test", "password": PASSWORD})).status_code, 429)

    async def test_missing_configuration_and_failed_delivery_fail_closed(self):
        with patch.dict(os.environ, {"SERVGO_EMAIL_AUTH_SECRET": ""}):
            self.assertFalse((await self.client.get("/auth/email/capabilities")).json()["available"])
            self.assertEqual((await self.client.post("/auth/email/login", json={"email": "owner@example.test", "password": PASSWORD})).status_code, 503)
        self.mail.return_value = False
        result = await self.client.post("/auth/email/start", json={"email": "owner@example.test", "purpose": "register", "password": PASSWORD, "full_name": "Demo"})
        self.assertEqual(result.status_code, 503)
        async with self.sessions() as db:
            challenge = await db.scalar(select(EmailChallenge))
            self.assertTrue(challenge.consumed)
            self.assertEqual(await db.scalar(select(func.count()).select_from(EmailIdentity)), 0)

    async def test_proof_is_durable_and_private_without_telegram(self):
        async with self.sessions() as db:
            (await db.get(User, self.owner)).telegram_id = -100000
            await db.commit()
        bid, token = await self.booking(receipt=True)
        self.assertEqual((await self.submit(token)).status_code, 200)
        self.assertEqual((await self.submit(token)).status_code, 200)
        details = await self.details(bid)
        self.assertEqual(len(details["receipts"]), 1)
        proof = details["receipts"][0]
        result = await self.client.get(f'/admin/receipts/{proof["id"]}', headers=self.owner_auth)
        self.assertEqual(result.content, PNG)
        self.assertEqual(result.headers["cache-control"], "private, no-store")
        self.assertEqual(result.headers["x-content-type-options"], "nosniff")
        self.assertEqual((await self.client.get(f'/admin/receipts/{proof["id"]}')).status_code, 401)
        self.assertEqual((await self.client.get(f'/admin/receipts/{proof["id"]}', headers=self.outsider_auth)).status_code, 404)
        wrong = await self.client.get(f'/admin/prepayments?business_id={self.business}', headers=self.outsider_auth)
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual((await self.client.get(f'/admin/bookings/{bid}/payment-details', headers=self.outsider_auth)).status_code, 404)

    async def test_invalid_proof_cannot_mark_payment_sent(self):
        bid, token = await self.booking(receipt=True)
        for invalid in [b"", b"<html>not a receipt</html>", b"x" * (10 * 1024 * 1024 + 1)]:
            self.assertEqual((await self.submit(token, invalid)).status_code, 422)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Booking, bid)).status, "pending_prepayment")
            self.assertEqual(await db.scalar(select(func.count()).select_from(BookingReceipt)), 0)

    async def test_owner_confirmation_is_audited_and_stale_decisions_fail(self):
        for rental, at in [(False, 11), (True, 14)]:
            bid, token = await self.booking(at=at, rental=rental)
            self.assertEqual((await self.submit(token)).status_code, 200)
            details = await self.details(bid)
            version = details["booking"]["version"]
            result = await self.decide(bid, "confirm", version)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["status"], "confirmed")
            self.assertEqual((await self.decide(bid, "reject", version)).status_code, 409)
            async with self.sessions() as db:
                row = await db.get(Booking, bid)
                self.assertIsNotNone(row.prepayment_confirmed_at)
                self.assertEqual((await db.scalar(select(PrepaymentReview).where(PrepaymentReview.booking_id == bid))).decision, "confirm")

    async def test_rejection_starts_fresh_window_preserves_proof_and_can_resubmit(self):
        bid, token = await self.booking(receipt=True)
        await self.submit(token)
        async with self.sessions() as db:
            (await db.get(Booking, bid)).prepayment_requested_at = datetime.utcnow() - timedelta(hours=1)
            await db.commit()
        version = (await self.details(bid))["booking"]["version"]
        result = await self.decide(bid, "reject", version)
        self.assertEqual(result.status_code, 200, result.text)
        async with self.sessions() as db:
            row = await db.get(Booking, bid)
            self.assertGreater(payment_deadline(row), datetime.utcnow() + timedelta(minutes=9))
            self.assertEqual(await expire_due_prepayments(db), [])
            await db.commit()
        self.assertEqual((await self.decide(bid, "reject", result.json()["version"])).status_code, 409)
        self.assertEqual((await self.submit(token)).status_code, 200)
        newer = await self.details(bid)
        self.assertEqual(len(newer["receipts"]), 2)
        self.assertEqual((await self.decide(bid, "confirm", version)).status_code, 409)
        self.assertEqual((await self.decide(bid, "confirm", newer["booking"]["version"])).status_code, 200)

    async def test_cancel_booking_is_separate_from_rejection_and_frees_slot(self):
        bid, token = await self.booking()
        await self.submit(token)
        result = await self.client.patch(f"/admin/bookings/{bid}/status", headers=self.owner_auth, json={"status": "cancelled"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "cancelled")
        self.assertEqual((await self.submit(token)).status_code, 409)
        details = await self.details(bid)
        self.assertEqual(details["reviews"][0]["decision"], "cancel")
        self.assertEqual(len(details["receipts"]), 1)

    async def test_generic_status_route_cannot_bypass_payment_review_or_expiry(self):
        bid, _ = await self.booking()
        for status in ["pending", "completed"]:
            self.assertEqual((await self.client.patch(f"/admin/bookings/{bid}/status", headers=self.owner_auth, json={"status": status})).status_code, 409)
        async with self.sessions() as db:
            (await db.get(Booking, bid)).prepayment_requested_at = datetime.utcnow() - timedelta(minutes=11)
            await db.commit()
        result = await self.client.patch(f"/admin/bookings/{bid}/status", headers=self.owner_auth, json={"status": "confirmed"})
        self.assertEqual(result.status_code, 409)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Booking, bid)).status, "cancelled")

    async def test_entire_multi_service_visit_is_protected_and_reviewed_together(self):
        first, token = await self.booking(at=11)
        second, _ = await self.booking(at=12)
        await self.submit(token)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Booking, second)).status, "prepayment_sent")
            self.assertEqual(await expire_due_prepayments(db, now=datetime.utcnow() + timedelta(hours=1)), [])
            await db.commit()
        details = await self.details(second)
        self.assertEqual(len(details["receipts"]), 1)
        result = await self.decide(second, "confirm", details["booking"]["version"])
        self.assertEqual(result.status_code, 200, result.text)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Booking, first)).status, "confirmed")
            self.assertEqual((await db.get(Booking, second)).status, "confirmed")
            self.assertEqual(await db.scalar(select(func.count()).select_from(PrepaymentReview)), 2)

    async def test_concurrent_review_only_records_one_decision(self):
        if not self.pg_schema: self.skipTest("PostgreSQL row-lock test")
        bid, token = await self.booking()
        await self.submit(token)
        version = (await self.details(bid))["booking"]["version"]
        results = await asyncio.gather(self.decide(bid, "confirm", version), self.decide(bid, "reject", version))
        self.assertEqual(sorted(r.status_code for r in results), [200, 409])
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(PrepaymentReview)), 1)

    async def test_inbox_filters_and_paginates_only_selected_business(self):
        bid, token = await self.booking()
        await self.submit(token)
        await self.booking(at=14)
        pending = await self.client.get(f"/admin/prepayments?business_id={self.business}", headers=self.owner_auth)
        self.assertEqual([b["id"] for b in pending.json()["items"]], [bid])
        page = await self.client.get(f"/admin/prepayments?business_id={self.business}&status=all&limit=1", headers=self.owner_auth)
        self.assertEqual(len(page.json()["items"]), 1)
        second = await self.client.get(f'/admin/prepayments?business_id={self.business}&status=all&limit=1&before_id={page.json()["next_before_id"]}', headers=self.owner_auth)
        self.assertEqual(second.json()["items"][0]["id"], bid)

    async def test_migration_is_additive_and_idempotent(self):
        if not self.pg_schema: self.skipTest("PostgreSQL migration")
        migration = Path("migrations/add_email_auth_and_payment_review.sql").read_text()
        async with self.engine.begin() as connection:
            for name in ["prepayment_reviews", "booking_receipts", "auth_rate_buckets", "email_challenges", "email_identities"]:
                await connection.execute(text(f"DROP TABLE {name}"))  # Only this test's UUID schema.
            for _ in range(2):
                for statement in migration.split(";"):
                    if statement.strip() and statement.strip() not in {"BEGIN", "COMMIT"}:
                        await connection.execute(text(statement))
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(User)), 3)
            self.assertEqual(await db.scalar(select(func.count()).select_from(BookingReceipt)), 0)

    async def test_bot_receipt_is_visible_in_web_inbox_and_reviewable(self):
        from bot.handlers import client as bot_client
        bid, _ = await self.booking(receipt=True)
        async def fake_download(file_id, destination):
            destination.write(PNG)
        message = SimpleNamespace(photo=[SimpleNamespace(file_id="test-proof", file_size=len(PNG))], document=None,
            from_user=SimpleNamespace(id=102), chat=SimpleNamespace(id=102), message_id=55,
            bot=SimpleNamespace(download=AsyncMock(side_effect=fake_download), copy_message=AsyncMock()), answer=AsyncMock())
        state = SimpleNamespace(get_data=AsyncMock(return_value={"prepayment_booking_id": bid}), clear=AsyncMock(), set_state=AsyncMock())
        with patch.object(bot_client, "async_session_maker", self.sessions):
            await bot_client.client_prepayment_receipt_uploaded(message, state)
        details = await self.details(bid)
        self.assertEqual(details["booking"]["status"], "prepayment_sent")
        self.assertEqual(len(details["receipts"]), 1)
        self.assertEqual((await self.decide(bid, "confirm", details["booking"]["version"])).status_code, 200)

    async def test_bot_cannot_claim_expired_payment_or_skip_required_receipt(self):
        from bot.handlers import client as bot_client
        bid, _ = await self.booking(receipt=True)
        callback = SimpleNamespace(data=f"prepay_sent:{bid}", from_user=SimpleNamespace(id=102), answer=AsyncMock(),
            message=SimpleNamespace(text="Booking", edit_text=AsyncMock()))
        state = SimpleNamespace(set_state=AsyncMock())
        with patch.object(bot_client, "async_session_maker", self.sessions):
            await bot_client.client_prepayment_sent(callback, state)
        self.assertIn("чек", callback.answer.call_args.args[0])
        async with self.sessions() as db:
            from database.models import Business
            (await db.get(Business, self.business)).require_receipt_for_prepayment = False
            (await db.get(Booking, bid)).prepayment_requested_at = datetime.utcnow() - timedelta(minutes=11)
            await db.commit()
        with patch.object(bot_client, "async_session_maker", self.sessions):
            await bot_client.client_prepayment_sent(callback, state)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Booking, bid)).status, "cancelled")
        callback.message.edit_text.assert_not_called()

    async def test_bot_reject_and_confirm_share_web_audit_and_block_old_buttons(self):
        from bot.handlers import admin as bot_admin
        bid, token = await self.booking()
        await self.submit(token)
        version = (await self.details(bid))["booking"]["version"]
        callback = SimpleNamespace(data=f"reject_prepayment:{bid}:{version}", from_user=SimpleNamespace(id=101), answer=AsyncMock(),
            bot=SimpleNamespace(send_message=AsyncMock()), message=SimpleNamespace(text="Booking", edit_text=AsyncMock()))
        state = SimpleNamespace()
        with patch.object(bot_admin, "async_session_maker", self.sessions), patch("bot.services.webpush.send_booking_status_webpush", AsyncMock()):
            await bot_admin.reject_prepayment_by_owner(callback, state)
        self.assertEqual((await self.details(bid))["reviews"][0]["decision"], "reject")
        await self.submit(token)
        callback.data = f"confirm_prepayment:{bid}:{version}"
        with patch.object(bot_admin, "async_session_maker", self.sessions):
            await bot_admin.confirm_prepayment_by_owner(callback, state)
        self.assertEqual((await self.details(bid))["booking"]["status"], "prepayment_sent")
        callback.data = f'confirm_prepayment:{bid}:{(await self.details(bid))["booking"]["version"]}'
        with patch.object(bot_admin, "async_session_maker", self.sessions):
            await bot_admin.confirm_prepayment_by_owner(callback, state)
        self.assertEqual((await self.details(bid))["booking"]["status"], "confirmed")

    async def test_concurrent_email_verification_creates_only_one_account(self):
        if not self.pg_schema: self.skipTest("PostgreSQL verification race")
        challenge, code = await self.begin()
        results = await asyncio.gather(self.verify(challenge, code), self.verify(challenge, code))
        self.assertEqual(sorted(r.status_code for r in results), [200, 400])
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(EmailIdentity)), 1)
            self.assertEqual(await db.scalar(select(func.count()).select_from(User)), 4)
