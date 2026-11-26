"""Offline-only regression for the production HTTP SEO smoke contract."""
import unittest

from scripts.seo_public_release_smoke import PublicResponse, verify

ROOT = "https://servgo.ru"
BID = 64
SLUG = "how-to-book"
ARTICLE = f"{ROOT}/business/{BID}/blog/{SLUG}"
SITEMAP = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    f'<sitemap><loc>{ROOT}/business/{BID}/blog/sitemap.xml</loc></sitemap>'
    '</sitemapindex>'
)
BUSINESS_MAP = (
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    f'<url><loc>{ARTICLE}</loc></url></urlset>'
)
HTML = (
    '<!doctype html><html lang="ru"><head>'
    f'<link rel="canonical" href="{ARTICLE}">'
    '<meta name="robots" content="index,follow,max-snippet:-1">'
    '<script type="application/ld+json">'
    f'{{"@type":"Article","url":"{ARTICLE}"}}'
    '</script></head><body><main><h1>Как записаться</h1>'
    '<p>Это полезное руководство по онлайн-записи клиентов, '
    'которое содержит достаточное описание процесса работы сервиса, '
    'примеры и пошаговые инструкции, а также ответы на частые вопросы.</p>'
    '<a href="/book/64">Записаться</a></main></body></html>'
)


def responses():
    return {
        "/robots.txt": PublicResponse(
            200, "text/plain",
            "User-agent: *\nAllow: /\nSitemap: https://servgo.ru/business-blog-sitemap.xml\n"),
        "/business-blog-sitemap.xml": PublicResponse(200, "application/xml", SITEMAP),
        f"/business/{BID}/blog/sitemap.xml": PublicResponse(200, "application/xml", BUSINESS_MAP),
        f"/business/{BID}/blog/{SLUG}": PublicResponse(200, "text/html; charset=utf-8", HTML),
        f"/business/{BID}/blog/__invalid_slug__": PublicResponse(404, "application/json", "{}"),
    }


class SeoPublicSmokeTests(unittest.TestCase):
    def test_read_only_discovery_and_complete_article(self):
        data = responses()
        self.assertEqual(verify(data.__getitem__)["search_indexing"], "not_measured")
        result = verify(data.__getitem__, business_id=BID, slug=SLUG)
        self.assertEqual(result["article"], "served_and_indexable_in_html")
        self.assertEqual(result["invalid_article"], "404")

    def test_robots_blocks_search_bot(self):
        data = responses()
        data["/robots.txt"] = PublicResponse(200, "text/plain",
            "User-agent: OAI-SearchBot\nDisallow: /\n"
            "User-agent: *\nAllow: /\n"
            "Sitemap: https://servgo.ru/business-blog-sitemap.xml\n")
        with self.assertRaisesRegex(RuntimeError, "OAI-SearchBot"):
            verify(data.__getitem__)

    def test_spa_or_wrong_canonical_fails(self):
        data = responses()
        data[f"/business/{BID}/blog/{SLUG}"] = PublicResponse(
            200, "text/html", HTML.replace(ARTICLE, ROOT + "/incorrect"))
        with self.assertRaisesRegex(RuntimeError, "Canonical"):
            verify(data.__getitem__, business_id=BID, slug=SLUG)

    def test_unknown_slug_must_return_real_404(self):
        data = responses()
        data[f"/business/{BID}/blog/__invalid_slug__"] = PublicResponse(
            200, "text/html", "<html>SPA fallback</html>")
        with self.assertRaisesRegex(RuntimeError, "Unknown article"):
            verify(data.__getitem__, business_id=BID, slug=SLUG)

    def test_sitemap_rejects_foreign_domain(self):
        data = responses()
        data["/business-blog-sitemap.xml"] = PublicResponse(
            200, "application/xml", SITEMAP.replace(ROOT, "https://elsewhere.example"))
        with self.assertRaisesRegex(RuntimeError, "unexpected URL"):
            verify(data.__getitem__)



class SeoLiveAuditTests(unittest.TestCase):
    def setUp(self):
        from scripts.ops import servgo_seo_live_audit as audit
        self.audit = audit
        audit.errors.clear()
        audit.DEADLINE = audit.time.monotonic() + 240

    def tearDown(self):
        self.audit.errors.clear()

    def test_header_blocks_indexing_even_with_indexable_html(self):
        from unittest.mock import patch
        from subprocess import CompletedProcess
        output = ("HTTP/2 200\ncontent-type: text/html; charset=utf-8\n"
                  "X-Robots-Tag: index, follow\nX-Robots-Tag: googlebot: noindex\n\n"
                  + HTML + "\n__HTTP_STATUS__=200")
        with patch.object(self.audit.subprocess, "run", return_value=CompletedProcess([], 0, output)):
            self.audit.inspect_html(f"/business/{BID}/blog/{SLUG}", expected=ARTICLE, require_ssr=True)
        self.assertTrue(any("X-Robots-Tag" in e for e in self.audit.errors))

    def test_meta_is_parsed_not_raw_word_search(self):
        parser = self.audit.IndexingMeta()
        parser.feed('<html><script>var x = "noindex";</script><p>noindex</p></html>')
        self.assertFalse(parser.blocked)
        parser.feed("<meta content='none' name='Googlebot'>")
        self.assertTrue(parser.blocked)

    def test_limit_does_not_report_complete_coverage(self):
        from unittest.mock import patch
        with patch.object(self.audit, "MAX_URLS", 1):
            self.assertEqual(self.audit.bounded(["/a", "/a", "/b"], "test"), ["/a"])
        self.assertTrue(any("coverage incomplete" in e for e in self.audit.errors))


if __name__ == "__main__":
    unittest.main()
