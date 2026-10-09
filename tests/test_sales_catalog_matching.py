"""Regression tests for catalog wording and safe provider connection reuse."""
import unittest
from types import SimpleNamespace

import httpx

from web.api.sales.service_match import normalized_tokens, rank_services, score_service
from web.api.sales.provider import ClaudeHubClient, LLMConfig


class CatalogMatchingTests(unittest.TestCase):
    def test_wheel_wash_matches_tire_wash_without_invented_service(self):
        service = SimpleNamespace(id=7, name="Помывка шин", description="", sort_order=0)
        other = SimpleNamespace(id=8, name="Замена масла", description="", sort_order=1)
        ranked = rank_services([other, service], "Хочу помывку колёс на 16 дюймов")
        self.assertTrue(ranked)
        self.assertEqual(ranked[0][0].id, 7)
        self.assertGreater(ranked[0][1], 0.5)

    def test_morphology_and_typo_are_suggestions_not_booking(self):
        services = [SimpleNamespace(id=2, name="Стрижка мужская", description="", sort_order=0),
                    SimpleNamespace(id=3, name="Маникюр", description="", sort_order=1)]
        self.assertEqual(rank_services(services, "хочу подстричься")[0][0].id, 2)
        self.assertGreater(score_service("маникюр", "Маникюр"), 0.9)
        self.assertEqual(rank_services(services, "маникур")[0][0].id, 3)
        self.assertEqual(rank_services(services, "ремонт компьютера"), [])
        self.assertIn("мойка", normalized_tokens("Помывка шин"))


class ProviderConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_rounds_share_one_http_client_and_close_it(self):
        requests = []
        async def respond(request):
            requests.append(request)
            return httpx.Response(200, json={"choices": [{"message": {
                "role": "assistant", "content": "Здравствуйте!"}}]})
        provider = ClaudeHubClient(
            LLMConfig(base_url="https://local.invalid", api_key="fake", model="gpt-6-luna"),
            transport=httpx.MockTransport(respond))
        try:
            result = await provider.complete([{"role": "user", "content": "Здравствуйте"}], [])
            first_client = provider._client
            await provider.complete([{"role": "user", "content": "Подскажите цену"}], [])
            self.assertIs(provider._client, first_client)
            self.assertEqual(len(requests), 2)
            self.assertEqual(result["content"], "Здравствуйте!")
        finally:
            await provider.aclose()
        self.assertTrue(first_client.is_closed)
