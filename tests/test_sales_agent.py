"""Sales chat regression suite. All customers/companies are synthetic; LLM calls are scripted."""
import asyncio
import hashlib
import hmac
import json
import os
import time as clock
import unittest
import uuid
from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import httpx
from fastapi import FastAPI
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, User, Business, Service, Employee, EmployeeDayOff, Booking, SalesConversation
from web.api.database import get_db
from web.api.deps import create_token
from web.api.routes import ai
from web.api.sales.provider import ClaudeHubClient, LLMConfig, ProviderError
from web.api.sales.state import trim_history


def call(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"id": name + "-call", "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)}}]}


class ScriptedProvider:
    def __init__(self, *responses, stage="closing"):
        self.responses = list(responses)
        self.requests = []
        self.stage = stage

    async def complete(self, messages, tools):
        self.requests.append((json.loads(json.dumps(messages)), tools))
        if messages[0]["content"].startswith("Определи следующую стадию"):
            return {"role": "assistant", "content": json.dumps({"stage": self.stage, "facts": {"need": "Расслабиться"}})}
        if self.responses:
            return self.responses.pop(0)
        return {"role": "assistant", "content": "Расскажите, что вам нужно."}


class SalesApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        test_url = os.getenv("SERVGO_SALES_TEST_POSTGRES_URL")
        self.pg_schema = None
        if test_url:
            # Isolate every test in a fresh schema, never delete pre-existing tables.
            self.pg_schema = "sales_test_" + uuid.uuid4().hex
            self.admin_engine = create_async_engine(test_url)
            async with self.admin_engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{self.pg_schema}"'))
            self.engine = create_async_engine(test_url, connect_args={
                "server_settings": {"search_path": self.pg_schema}})
        else:
            self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.day = date.today() + timedelta(days=3)
        async with self.sessions() as db:
            owner = User(telegram_id=101, full_name="Демо владелец")
            customer = User(telegram_id=102, full_name="Демо клиент", phone="+79990000001")
            outsider = User(telegram_id=103, full_name="Другой клиент", phone="+79990000002")
            db.add_all([owner, customer, outsider]); await db.flush()
            self.owner, self.customer, self.outsider = owner.id, customer.id, outsider.id
            business = Business(owner_id=owner.id, name="Демо массаж", business_type="salon",
                description="Каталог массажа", ai_instruction="TENANT_ONE_ONLY", is_active=True,
                working_hours_start=time(9), working_hours_end=time(20), booking_interval_minutes=30)
            other = Business(owner_id=outsider.id, name="Другая компания", business_type="salon",
                ai_instruction="TENANT_TWO_SECRET_RULES", is_active=True)
            db.add_all([business, other]); await db.flush()
            self.business, self.other_business = business.id, other.id
            service = Service(business_id=business.id, name="Расслабляющий массаж", description="Мягкий массаж",
                duration_minutes=60, price=4000, is_active=True, is_additional=False)
            other_service = Service(business_id=other.id, name="Чужая услуга", duration_minutes=30, price=9900)
            employee = Employee(business_id=business.id, name="Демо мастер", role="master", is_active=True)
            other_employee = Employee(business_id=other.id, name="Чужой мастер", role="master", is_active=True)
            db.add_all([service, other_service, employee, other_employee]); await db.commit()
            self.service, self.other_service = service.id, other_service.id
            self.employee, self.other_employee = employee.id, other_employee.id
        self.app = FastAPI(); self.app.include_router(ai.router)
        async def get_session():
            async with self.sessions() as db:
                yield db
        self.app.dependency_overrides[get_db] = get_session
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="https://test.local")
        self.auth = {"Authorization": "Bearer " + create_token(self.customer)}
        self.owner_auth = {"Authorization": "Bearer " + create_token(self.owner)}
        self.outsider_auth = {"Authorization": "Bearer " + create_token(self.outsider)}
        self.events = [patch("web.api.routes.client.notify_created_visit", new=AsyncMock()),
                       patch("web.api.rental.notify_rental_request", new=AsyncMock())]
        for event in self.events: event.start()

    async def asyncTearDown(self):
        for event in self.events: event.stop()
        await self.client.aclose(); await self.engine.dispose()
        if self.pg_schema:
            async with self.admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{self.pg_schema}" CASCADE'))
            await self.admin_engine.dispose()

    def booking_args(self, **changes):
        args = {"service_id": self.service, "employee_id": self.employee, "date": str(self.day), "time": "18:30"}
        args.update(changes); return args

    async def propose(self, headers=None, **changes):
        provider = ScriptedProvider(call("create_booking", **self.booking_args(**changes)))
        with patch.object(ai, "ClaudeHubClient", return_value=provider):
            result = await self.client.post("/ai/chat", headers=self.auth if headers is None else headers,
                json={"business_id": self.business, "message": "Запишите на 18:30"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()["pending_action"], result.text)
        return result.json()["pending_action"]

    async def booking_count(self):
        async with self.sessions() as db:
            return await db.scalar(select(func.count()).select_from(Booking))

    async def test_sales_tools_to_atomic_booking_and_replay(self):
        provider = ScriptedProvider(call("get_services"), call("get_service_details", service_id=self.service),
            call("get_prices", service_id=self.service), call("get_specialists", service_id=self.service),
            call("check_availability", service_id=self.service, employee_id=self.employee, date=str(self.day)),
            call("create_booking", **self.booking_args()))
        with patch.object(ai, "ClaudeHubClient", return_value=provider):
            chat = await self.client.post("/ai/chat", headers=self.auth,
                json={"business_id": self.business, "message": "Хочу расслабиться и записаться"})
        self.assertEqual(chat.status_code, 200, chat.text)
        action = chat.json()["pending_action"]
        self.assertIn("4000 ₽", action["description"])
        self.assertEqual(await self.booking_count(), 0)
        payload = {"action_id": action["action_id"]}
        confirmed = await self.client.post("/ai/confirm", headers=self.auth, json=payload)
        replay = await self.client.post("/ai/confirm", headers=self.auth, json=payload)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json(), replay.json())
        self.assertEqual(confirmed.json()["stage"], "booked")
        self.assertEqual(await self.booking_count(), 1)
        self.assertTrue(confirmed.json()["booking_url"].startswith("/b/"))
        history = await self.client.get("/ai/history", headers=self.auth, params={"business_id": self.business})
        self.assertIn("Запись создана", history.json()["messages"][-1]["text"])
        async with self.sessions() as db:
            conversation = (await db.execute(select(SalesConversation))).scalar_one()
            self.assertEqual(conversation.facts["need"], "Расслабиться")
            self.assertEqual(conversation.action["status"], "completed")
            booking = (await db.execute(select(Booking))).scalar_one()
            self.assertEqual(booking.client_id, self.customer)

    async def test_history_is_durable_and_isolated_between_businesses(self):
        await self.propose()
        history = await self.client.get("/ai/history", headers=self.auth, params={"business_id": self.business})
        self.assertTrue(history.json()["pending_action"])
        other = await self.client.get("/ai/history", headers=self.auth, params={"business_id": self.other_business})
        self.assertEqual(other.json()["messages"], [])
        provider = ScriptedProvider(call("get_services"), {"role": "assistant", "content": "Вот каталог"})
        with patch.object(ai, "ClaudeHubClient", return_value=provider):
            await self.client.post("/ai/chat", headers=self.auth, json={"business_id": self.business, "message": "Покажите услуги"})
        sent = json.dumps(provider.requests, ensure_ascii=False)
        self.assertIn("TENANT_ONE_ONLY", sent)
        self.assertNotIn("TENANT_TWO_SECRET_RULES", sent)
        self.assertNotIn("Чужая услуга", sent)

    async def test_cross_tenant_service_resource_and_extra_identity_are_rejected(self):
        for args in (self.booking_args(service_id=self.other_service), self.booking_args(employee_id=self.other_employee),
                     self.booking_args(business_id=self.other_business), self.booking_args(client_id=self.outsider)):
            provider = ScriptedProvider(call("create_booking", **args), {"role": "assistant", "content": "Выберите другой вариант"})
            with patch.object(ai, "ClaudeHubClient", return_value=provider):
                result = await self.client.post("/ai/chat", headers=self.auth, json={"business_id": self.business, "message": "Запишите"})
            self.assertEqual(result.status_code, 200)
            self.assertIsNone(result.json()["pending_action"])
        self.assertEqual(await self.booking_count(), 0)

    async def test_unauthorized_confirm_and_reject_do_not_consume_action(self):
        action = await self.propose()
        for endpoint in ("confirm", "reject"):
            result = await self.client.post("/ai/" + endpoint, headers=self.outsider_auth, json={"action_id": action["action_id"]})
            self.assertEqual(result.status_code, 404)
        result = await self.client.post("/ai/confirm", headers=self.auth, json={"action_id": action["action_id"]})
        self.assertEqual(result.status_code, 200, result.text)

    async def test_expired_confirmation_is_hidden_and_cannot_book(self):
        action = await self.propose()
        async with self.sessions() as db:
            row = (await db.execute(select(SalesConversation))).scalar_one()
            row.action = {**row.action, "expires_at": (datetime.utcnow() - timedelta(seconds=1)).isoformat()}
            await db.commit()
        result = await self.client.post("/ai/confirm", headers=self.auth, json={"action_id": action["action_id"]})
        self.assertEqual(result.status_code, 410)
        history = await self.client.get("/ai/history", headers=self.auth, params={"business_id": self.business})
        self.assertIsNone(history.json()["pending_action"])
        self.assertEqual(await self.booking_count(), 0)

    async def test_price_change_requires_new_confirmation(self):
        action = await self.propose()
        async with self.sessions() as db:
            (await db.get(Service, self.service)).price = 5000; await db.commit()
        result = await self.client.post("/ai/confirm", headers=self.auth, json={"action_id": action["action_id"]})
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(await self.booking_count(), 0)

    async def test_slot_taken_after_proposal_is_rejected(self):
        action = await self.propose()
        async with self.sessions() as db:
            db.add(Booking(business_id=self.business, client_id=self.outsider, service_id=self.service,
                employee_id=self.employee, booking_date=self.day, booking_time=time(18), status="confirmed",
                resource_duration_minutes=60, occupies_resource=True))
            await db.commit()
        result = await self.client.post("/ai/confirm", headers=self.auth, json={"action_id": action["action_id"]})
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(await self.booking_count(), 1)

    async def test_day_off_and_past_date_cannot_be_proposed(self):
        async with self.sessions() as db:
            db.add(EmployeeDayOff(employee_id=self.employee, date=self.day)); await db.commit()
        for day in (self.day, date.today() - timedelta(days=1)):
            provider = ScriptedProvider(call("create_booking", **self.booking_args(date=str(day))), {"role": "assistant", "content": "Выберите другую дату"})
            with patch.object(ai, "ClaudeHubClient", return_value=provider):
                result = await self.client.post("/ai/chat", headers=self.auth, json={"business_id": self.business, "message": "Запишите"})
            self.assertIsNone(result.json()["pending_action"])

    async def test_guest_cookie_is_stable_and_booking_requires_contact(self):
        action = await self.propose(headers={})
        self.assertTrue(action["requires_contact"])
        first_cookie = self.client.cookies.get(ai.COOKIE_NAME)
        self.assertTrue(first_cookie)
        history = await self.client.get("/ai/history", params={"business_id": self.business})
        self.assertEqual(history.json()["pending_action"]["action_id"], action["action_id"])
        missing = await self.client.post("/ai/confirm", json={"action_id": action["action_id"]})
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(await self.booking_count(), 0)
        confirmed = await self.client.post("/ai/confirm", json={"action_id": action["action_id"],
            "client_name": "Демо гость", "client_phone": "+79990000003"})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(self.client.cookies.get(ai.COOKIE_NAME), first_cookie)
        async with self.sessions() as db:
            user = await db.get(User, (await db.execute(select(Booking))).scalar_one().client_id)
            self.assertEqual(user.phone, "+79990000003")

    async def test_guest_history_is_not_shared_with_another_browser(self):
        await self.propose(headers={})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="https://test.local") as other:
            result = await other.get("/ai/history", params={"business_id": self.business})
        self.assertEqual(result.json()["messages"], [])

    async def test_handoff_stops_ai_and_owner_can_reply_and_resume(self):
        await self.propose()
        provider = ScriptedProvider(call("handoff_to_human", reason="Клиент попросил оператора"))
        with patch.object(ai, "ClaudeHubClient", return_value=provider) as factory:
            result = await self.client.post("/ai/chat", headers=self.auth, json={"business_id": self.business, "message": "Позовите человека"})
            followup = await self.client.post("/ai/chat", headers=self.auth, json={"business_id": self.business, "message": "Уточнение оператору"})
            self.assertEqual(factory.call_count, 1)
        self.assertEqual(result.json()["mode"], "human")
        self.assertIsNone(result.json()["pending_action"])
        self.assertEqual(followup.json()["mode"], "human")
        inbox = await self.client.get(f"/admin/ai/businesses/{self.business}/conversations", headers=self.owner_auth)
        conversation_id = inbox.json()[0]["id"]
        denied = await self.client.post(f"/admin/ai/conversations/{conversation_id}/reply", headers=self.outsider_auth, json={"message": "Неверный оператор"})
        self.assertEqual(denied.status_code, 403)
        replied = await self.client.post(f"/admin/ai/conversations/{conversation_id}/reply", headers=self.owner_auth, json={"message": "Здравствуйте, я оператор"})
        self.assertEqual(replied.status_code, 200)
        history = await self.client.get("/ai/history", headers=self.auth, params={"business_id": self.business})
        self.assertEqual(history.json()["messages"][-1]["text"], "Здравствуйте, я оператор")
        resumed = await self.client.post(f"/admin/ai/conversations/{conversation_id}/resume", headers=self.owner_auth)
        self.assertEqual(resumed.status_code, 200)
        history = await self.client.get("/ai/history", headers=self.auth, params={"business_id": self.business})
        self.assertEqual(history.json()["mode"], "ai")

    async def test_handoff_button_works_without_llm_credentials(self):
        with patch.object(ai, "ClaudeHubClient", side_effect=ProviderError("Not configured")) as factory:
            result = await self.client.post("/ai/handoff", headers=self.auth, json={"business_id": self.business})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["mode"], "human")
            factory.assert_not_called()

    async def test_legal_checkboxes_are_separate_and_saved(self):
        async with self.sessions() as db:
            business = await db.get(Business, self.business)
            business.legal_documents_enabled = True
            business.legal_name, business.legal_email = "Демо ООО", "demo@example.test"
            await db.commit()
        action = await self.propose()
        self.assertTrue(action["requires_legal_consent"])
        missing = await self.client.post("/ai/confirm", headers=self.auth, json={"action_id": action["action_id"], "personal_data_consent": True})
        self.assertEqual(missing.status_code, 422)
        confirmed = await self.client.post("/ai/confirm", headers=self.auth, json={"action_id": action["action_id"], "personal_data_consent": True, "booking_terms_accepted": True})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        async with self.sessions() as db:
            booking = (await db.execute(select(Booking))).scalar_one()
            self.assertIsNotNone(booking.personal_data_consent_at)
            self.assertIsNotNone(booking.booking_terms_accepted_at)

    async def test_rental_reuses_quote_duration_and_authenticated_customer(self):
        async with self.sessions() as db:
            (await db.get(Business, self.business)).business_type = "venue_rental"
            (await db.get(Employee, self.employee)).solo_price_per_hour = 19000
            await db.commit()
        action = await self.propose(time="11:00", duration_hours=5)
        self.assertIn("95000 ₽", action["description"])
        self.assertIn("300 мин", action["description"])
        confirmed = await self.client.post("/ai/confirm", headers=self.auth, json={"action_id": action["action_id"]})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertTrue(confirmed.json()["booking_url"].startswith("/rental/b/"))
        async with self.sessions() as db:
            booking = (await db.execute(select(Booking))).scalar_one()
            self.assertEqual((booking.client_id, booking.duration_minutes, booking.estimated_price), (self.customer, 300, 95000))
            self.assertIsNone(booking.prepayment_amount)

    async def test_short_rental_price_requires_manager_confirmation(self):
        async with self.sessions() as db:
            (await db.get(Business, self.business)).business_type = "venue_rental"
            (await db.get(Employee, self.employee)).solo_price_per_hour = 19000
            await db.commit()
        action = await self.propose(time="11:00", duration_hours=3)
        self.assertIn("цену подтверждает менеджер", action["description"])

    async def test_rejected_and_superseded_actions_cannot_book(self):
        first = await self.propose()
        second = await self.propose(time="11:00")
        old = await self.client.post("/ai/confirm", headers=self.auth, json={"action_id": first["action_id"]})
        self.assertEqual(old.status_code, 404)
        rejected = await self.client.post("/ai/reject", headers=self.auth, json={"action_id": second["action_id"]})
        self.assertEqual(rejected.status_code, 200)
        result = await self.client.post("/ai/confirm", headers=self.auth, json={"action_id": second["action_id"]})
        self.assertEqual(result.status_code, 409)

    async def test_model_errors_unknown_tools_and_loop_budget_are_safe(self):
        invalid = {"role": "assistant", "content": "", "tool_calls": [{"id": "bad", "function": {"name": "create_booking", "arguments": "{"}}]}
        provider = ScriptedProvider(invalid, call("delete_business"), {"role": "assistant", "content": "Уточните запрос"}, stage="invented_stage")
        with patch.object(ai, "ClaudeHubClient", return_value=provider):
            result = await self.client.post("/ai/chat", headers=self.auth, json={"business_id": self.business, "message": "Помогите"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["stage"], "needs_analysis")
        provider = ScriptedProvider(*(call("get_services") for _ in range(10)))
        with patch.object(ai, "ClaudeHubClient", return_value=provider):
            result = await self.client.post("/ai/chat", headers=self.auth, json={"business_id": self.business, "message": "Помогите"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(provider.requests), 7)  # analyzer + six tool rounds
        self.assertEqual(await self.booking_count(), 0)

    async def test_provider_failure_rolls_back_the_whole_turn(self):
        class FailedProvider(ScriptedProvider):
            async def complete(self, messages, tools):
                raise ProviderError("Тестовая недоступность")
        with patch.object(ai, "ClaudeHubClient", return_value=FailedProvider()):
            result = await self.client.post("/ai/chat", headers=self.auth, json={"business_id": self.business, "message": "Помогите"})
        self.assertEqual(result.status_code, 503)
        history = await self.client.get("/ai/history", headers=self.auth, params={"business_id": self.business})
        self.assertEqual(history.json()["messages"], [])

    async def test_telegram_data_requires_fresh_auth_date_and_signature(self):
        token = "telegram-test-only"
        def signed(auth_date):
            data = {"auth_date": str(auth_date), "user": json.dumps({"id": 102, "first_name": "Демо"})}
            secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
            data["hash"] = hmac.new(secret, "\n".join(f"{k}={v}" for k, v in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
            return urlencode(data)
        with patch.dict(os.environ, {"BOT_TOKEN": token}):
            for value in (signed(int(clock.time()) - 90000), signed(int(clock.time()) + 120), "hash=bad"):
                result = await self.client.get("/ai/history", headers={"X-Telegram-Init-Data": value}, params={"business_id": self.business})
                self.assertEqual(result.status_code, 401)
            result = await self.client.get("/ai/history", headers={"X-Telegram-Init-Data": signed(int(clock.time()))}, params={"business_id": self.business})
            self.assertEqual(result.status_code, 200)

    @unittest.skipUnless(os.getenv("SERVGO_SALES_TEST_POSTGRES_URL"), "Requires isolated PostgreSQL test database")
    async def test_parallel_confirmation_is_atomic_across_sessions(self):
        action = await self.propose()
        results = await asyncio.gather(*(self.client.post("/ai/confirm", headers=self.auth,
            json={"action_id": action["action_id"]}) for _ in range(4)))
        self.assertEqual([r.status_code for r in results], [200] * 4)
        self.assertTrue(all(r.json() == results[0].json() for r in results))
        self.assertEqual(await self.booking_count(), 1)

    @unittest.skipUnless(os.getenv("SERVGO_SALES_TEST_POSTGRES_URL"), "Requires isolated PostgreSQL test database")
    async def test_competing_customers_cannot_reserve_same_resource(self):
        first = await self.propose()
        second = await self.propose(headers=self.outsider_auth)
        results = await asyncio.gather(
            self.client.post("/ai/confirm", headers=self.auth, json={"action_id": first["action_id"]}),
            self.client.post("/ai/confirm", headers=self.outsider_auth, json={"action_id": second["action_id"]}))
        self.assertEqual(sorted(r.status_code for r in results), [200, 409])
        self.assertEqual(await self.booking_count(), 1)

    @unittest.skipUnless(os.getenv("SERVGO_SALES_TEST_POSTGRES_URL"), "Requires isolated PostgreSQL test database")
    async def test_concurrent_first_messages_share_one_durable_thread(self):
        provider = ScriptedProvider()
        with patch.object(ai, "ClaudeHubClient", return_value=provider):
            results = await asyncio.gather(*(self.client.post("/ai/chat", headers=self.auth,
                json={"business_id": self.business, "message": f"Сообщение {n}"}) for n in range(3)))
        self.assertTrue(all(r.status_code == 200 for r in results))
        self.assertEqual(len({r.json()["conversation_id"] for r in results}), 1)
        history = await self.client.get("/ai/history", headers=self.auth, params={"business_id": self.business})
        self.assertEqual(sum(m["role"] == "user" for m in history.json()["messages"]), 3)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_gateway_keeps_tool_protocol(self):
        async def upstream(request):
            self.assertEqual(str(request.url), "https://hub.example.test/v1/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer test-only")
            payload = json.loads(request.content)
            self.assertIn("tools", payload)
            return httpx.Response(200, json={"choices": [{"message": call("get_services")} ]})
        provider = ClaudeHubClient(LLMConfig("https://hub.example.test/v1", "test-only", "test-model"), httpx.MockTransport(upstream))
        from web.api.sales.tools import TOOL_SCHEMAS
        result = await provider.complete([{"role": "system", "content": "Демо"}, {"role": "user", "content": "Каталог"}], TOOL_SCHEMAS)
        self.assertEqual(result["tool_calls"][0]["function"]["name"], "get_services")

    async def test_anthropic_roundtrip_converts_all_tool_results(self):
        async def upstream(request):
            self.assertEqual(str(request.url), "https://hub.example.test/v1/messages")
            self.assertEqual(request.headers["x-api-key"], "test-only")
            payload = json.loads(request.content)
            self.assertEqual(payload["messages"][-1]["content"][0]["type"], "tool_result")
            self.assertEqual(payload["messages"][-1]["content"][0]["tool_use_id"], "get_services-call")
            return httpx.Response(200, json={"content": [{"type": "text", "text": "Вот услуги"},
                {"type": "tool_use", "id": "second", "name": "get_prices", "input": {"service_id": 1}}]})
        provider = ClaudeHubClient(LLMConfig("https://hub.example.test/v1", "test-only", "test-model", "anthropic"), httpx.MockTransport(upstream))
        result = await provider.complete([{"role": "system", "content": "Демо"}, {"role": "user", "content": "Каталог"},
            call("get_services"), {"role": "tool", "tool_call_id": "get_services-call", "content": "{}"}], [])
        self.assertEqual(result["content"], "Вот услуги")
        self.assertEqual(json.loads(result["tool_calls"][0]["function"]["arguments"]), {"service_id": 1})

    async def test_upstream_error_does_not_leak_credentials_or_response_body(self):
        provider = ClaudeHubClient(LLMConfig("https://hub.example.test/v1", "test-only", "test-model"),
            httpx.MockTransport(lambda request: httpx.Response(401, text="PRIVATE-UPSTREAM-DATA")))
        with self.assertRaises(ProviderError) as result:
            await provider.complete([], [])
        self.assertNotIn("PRIVATE", str(result.exception))
        self.assertNotIn("test-only", str(result.exception))


class HistoryTests(unittest.TestCase):
    def test_compaction_keeps_complete_tool_call_groups(self):
        history = []
        for number in range(20):
            history.extend([{"role": "user", "content": str(number)}, call("get_services"),
                {"role": "tool", "tool_call_id": "get_services-call", "content": "{}"},
                {"role": "assistant", "content": "Услуги"}])
        trimmed = trim_history(history, max_turns=3)
        self.assertEqual(trimmed[0]["content"], "17")
        self.assertEqual(len(trimmed), 12)
        self.assertEqual(trimmed[2]["role"], "tool")


if __name__ == "__main__":
    unittest.main()
