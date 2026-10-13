"""Focused regression tests for the public ServGo blog.

Run locally: pytest -q tests/test_public_blog.py
No external services or database required.
"""
import json
import re
from pathlib import Path

import jinja2

from webapp.blog_content import (
    BLOG_ARTICLES, BLOG_ARTICLES_BY_SLUG, BLOG_CATEGORIES,
    filter_blog_articles,
)

ROOT = Path(__file__).resolve().parents[1]


def _render(article=None, query="", topic="all", articles=None):
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(ROOT / "webapp" / "templates")),
        autoescape=jinja2.select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    base = "https://promo.servgo.ru"
    slug = "/blog" + ("/" + article["slug"] if article else "")
    return env.get_template("blog.html").render(
        origin=base,
        canonical=base + slug,
        article=article,
        articles=list(BLOG_ARTICLES if articles is None else articles),
        related=[a for a in BLOG_ARTICLES if a != article][:2],
        categories=BLOG_CATEGORIES,
        selected_topic=topic,
        query=query,
    )


def test_blog_slugs_unique_and_publication_data():
    assert len(BLOG_ARTICLES) >= 3
    assert len(BLOG_ARTICLES_BY_SLUG) == len(BLOG_ARTICLES)
    for article in BLOG_ARTICLES:
        assert re.fullmatch(r"[a-z0-9-]+", article["slug"])
        assert article["title"] and article["description"] and article["lead"]
        assert article["sections"]
        for section in article["sections"]:
            assert section["title"] and section["paragraphs"]


def test_blog_category_filter_and_search():
    assert len(filter_blog_articles("all")) == len(BLOG_ARTICLES)
    assert filter_blog_articles("not-a-topic") == list(BLOG_ARTICLES)
    assert all(a["topic"] == "booking" for a in filter_blog_articles("booking"))
    assert filter_blog_articles(query="ОНЛАЙН-ЗАПИСЬ")
    assert filter_blog_articles(query="word_that_does_not_exist") == []


def test_index_render_is_server_side_and_has_internal_links():
    html = _render()
    assert "<h1" in html
    assert 'rel="canonical" href="https://promo.servgo.ru/blog"' in html
    assert 'href="/blog/ai-marketing-for-small-business"' in html
    assert 'role="search"' in html
    assert 'href="/#launch"' in html
    assert '"/blog' not in html  # JSON-LD absolute URLs only


def test_article_pages_have_readable_content_and_valid_json_ld():
    for article in BLOG_ARTICLES:
        html = _render(article=article)
        assert f'/{article["slug"]}' in html
        assert "<h1>" + article["title"] + "</h1>" in html
        assert 'aria-label="Оглавление статьи"' in html
        assert "id=\"section-1\"" in html
        scripts = re.findall(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', html, re.S)
        assert len(scripts) == 1
        schema = json.loads(scripts[0])
        assert schema["@type"] == "BlogPosting"
        assert schema["headline"] == article["title"]
        assert schema["mainEntityOfPage"]["@id"].endswith(article["slug"])


def test_search_value_is_escaped_and_empty_state_honest():
    html = _render(query='"><script>alert(1)</script>', articles=[])
    assert '<script>alert(1)</script>' not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Пока ничего не нашли" in html
