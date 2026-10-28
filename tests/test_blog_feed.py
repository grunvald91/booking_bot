"""Блог на servgo.ru: статьи платформы, FAQ-разметка, llms.txt, карта сайта, редирект."""
import os
os.environ.setdefault('BOT_TOKEN', '123:test')
os.environ.setdefault('DATABASE_URL', 'sqlite+aiosqlite:///:memory:')

import json
import re
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from webapp import blog_feed
from webapp.server import create_webapp

RAW = {
    "slug": "kak-vybrat-crm", "title": "Как выбрать CRM для салона",
    "description": "Короткий разбор выбора CRM.", "category": "Сравнение и выбор",
    "lead": "Выбор CRM начинается с процессов салона.",
    "direct_answer": "Выбирайте CRM по тому, как у вас устроена запись.",
    "sections": [{"title": "С чего начать", "paragraphs": ["Опишите процесс."], "bullets": ["Запись", "Напоминания"]}],
    "closing": "Начните с малого.",
    "faq": [{"question": "Нужна ли CRM салону?", "answer": "Нужна, если записей больше десятка в день и есть повторные клиенты."}],
    "cta": "Подключить запись", "published_at": "2026-10-28T09:00:00+00:00", "updated_at": "2026-10-28T10:00:00+00:00",
}


async def fake_feed(*a, **k):
    article = blog_feed.normalize(RAW)
    return [article]


class NormalizeTest(unittest.TestCase):
    def test_valid_item(self):
        a = blog_feed.normalize(RAW)
        self.assertEqual(a["updated"], "2026-10-28")
        self.assertEqual(a["date_label"], "28 октября 2026")
        self.assertTrue(a["from_feed"])

    def test_broken_items_dropped(self):
        self.assertIsNone(blog_feed.normalize({**RAW, "slug": "../x"}))
        self.assertIsNone(blog_feed.normalize({**RAW, "sections": []}))
        self.assertIsNone(blog_feed.normalize({"slug": "a"}))


class BlogFeedPagesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patch = patch('webapp.blog_feed.feed_articles', fake_feed)
        self.patch.start()

    async def asyncTearDown(self):
        self.patch.stop()

    async def test_article_has_answer_faq_and_jsonld(self):
        async with TestClient(TestServer(create_webapp())) as c:
            res = await c.get('/blog/kak-vybrat-crm')
            html = await res.text()
        self.assertEqual(res.status, 200)
        self.assertIn('Выбирайте CRM по тому', html)
        self.assertIn('Частые вопросы', html)
        types = [json.loads(m)["@type"] for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
        self.assertEqual(types, ["BlogPosting", "FAQPage"])
        self.assertIn('rel="canonical" href="https://servgo.ru/blog/kak-vybrat-crm"', html)

    async def test_list_sitemap_and_llms(self):
        async with TestClient(TestServer(create_webapp())) as c:
            self.assertIn('kak-vybrat-crm', await (await c.get('/blog')).text())
            self.assertIn('https://servgo.ru/blog/kak-vybrat-crm', await (await c.get('/blog/sitemap.xml')).text())
            llms = await (await c.get('/llms.txt')).text()
            robots = await (await c.get('/robots.txt')).text()
        self.assertIn('[Как выбрать CRM для салона](https://servgo.ru/blog/kak-vybrat-crm)', llms)
        self.assertIn('https://servgo.ru/blog/sitemap.xml', robots)

    async def test_builtin_articles_keep_working_when_feed_down(self):
        self.patch.stop()
        blog_feed.reset_cache()
        with patch('webapp.blog_feed._download', side_effect=OSError):
            async with TestClient(TestServer(create_webapp())) as c:
                res = await c.get('/blog')
        self.patch.start()
        self.assertEqual(res.status, 200)

    async def test_unknown_slug_404(self):
        async with TestClient(TestServer(create_webapp())) as c:
            self.assertEqual((await c.get('/blog/net-takoj')).status, 404)

    async def test_old_promo_host_redirects(self):
        async with TestClient(TestServer(create_webapp())) as c:
            res = await c.get('/blog/kak-vybrat-crm', headers={'Host': 'promo.servgo.ru'}, allow_redirects=False)
        self.assertEqual(res.status, 301)
        self.assertEqual(res.headers['Location'], 'https://servgo.ru/blog/kak-vybrat-crm')


if __name__ == '__main__':
    unittest.main()
