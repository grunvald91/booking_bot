"""Каждый лендинг ниши рендерится: YAML-данные согласованы с шаблоном niche.html."""
import os
os.environ.setdefault('BOT_TOKEN', '123:test')
os.environ.setdefault('DATABASE_URL', 'sqlite+aiosqlite:///:memory:')

import unittest
from aiohttp.test_utils import TestClient, TestServer

from webapp.server import create_webapp
from webapp.niches import list_niches


class NicheLandingsRenderTest(unittest.IsolatedAsyncioTestCase):
    async def test_every_niche_renders(self):
        async with TestClient(TestServer(create_webapp())) as client:
            for slug in list_niches():
                res = await client.get(f'/{slug}')
                self.assertEqual(res.status, 200, f'/{slug}')


if __name__ == '__main__':
    unittest.main()
