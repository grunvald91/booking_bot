"""Статьи блога, опубликованные платформой AI Growth OS (growth.servgo.ru).

Платформа отдаёт только опубликованные статьи через публичную read-only ленту.
Блог берёт их оттуда, кэширует в памяти и, если лента недоступна, продолжает
показывать последнюю удачную копию или встроенные статьи. Ленту нельзя использовать
для подмены встроенных статей: при совпадении slug побеждает встроенная.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)

GROWTH_FEED_BASE = os.getenv(
    "BLOG_FEED_URL", "https://growth.servgo.ru/public/blog/servgo/articles"
).rstrip("/")
FEED_TTL_SECONDS = int(os.getenv("BLOG_FEED_TTL", "300"))
FEED_TIMEOUT_SECONDS = 5
_SLUG = re.compile(r"^[a-z0-9-]{1,120}$")
_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
_TOPIC = {"Советы": "marketing", "Сравнение и выбор": "growth", "Запуск": "booking"}

_cache: dict = {"at": 0.0, "articles": []}


def _date(value: str) -> tuple[str, str]:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.date().isoformat(), f"{parsed.day} {_MONTHS[parsed.month - 1]} {parsed.year}"


def normalize(raw: dict) -> dict | None:
    """Приводит запись ленты к форме встроенных статей; битые записи отбрасывает."""
    try:
        slug = str(raw["slug"])
        if not _SLUG.match(slug):
            return None
        title, lead = str(raw["title"]).strip(), str(raw["lead"]).strip()
        updated, label = _date(str(raw.get("updated_at") or raw["published_at"]))
        sections = [
            {
                "title": str(s["title"]),
                "paragraphs": [str(p) for p in s.get("paragraphs", [])],
                "bullets": [str(b) for b in s.get("bullets", [])],
            }
            for s in raw.get("sections", [])
        ]
        faq = [
            {"question": str(i["question"]), "answer": str(i["answer"])}
            for i in raw.get("faq", [])
        ]
        category = str(raw.get("category") or "Советы")
        if not title or not lead or not sections:
            return None
        return {
            "slug": slug,
            "from_feed": True,
            "title": title,
            "description": str(raw.get("description") or lead)[:300],
            "lead": lead,
            "category": category,
            "topic": _TOPIC.get(category, "growth"),
            "updated": updated,
            "published": _date(str(raw.get("published_at") or updated))[0],
            "date_label": label,
            "direct_answer": str(raw.get("direct_answer") or "").strip(),
            "sections": sections,
            "closing": str(raw.get("closing") or "").strip(),
            "faq": faq,
            "primary_query": str(raw.get("primary_query") or ""),
            "cta_text": str(raw.get("cta") or "") or None,
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


async def _download(session: aiohttp.ClientSession) -> list[dict]:
    async with session.get(GROWTH_FEED_BASE) as response:
        response.raise_for_status()
        items = (await response.json()).get("articles", [])
    articles = []
    for item in items:
        slug = str(item.get("slug", ""))
        if not _SLUG.match(slug):
            continue
        async with session.get(f"{GROWTH_FEED_BASE}/{slug}") as response:
            if response.status != 200:
                continue
            article = normalize(await response.json())
        if article:
            articles.append(article)
    return articles


async def feed_articles(*, now: float | None = None) -> list[dict]:
    """Опубликованные платформой статьи; при сбое — последняя удачная копия или пусто."""
    moment = time.monotonic() if now is None else now
    if _cache["at"] and moment - _cache["at"] < FEED_TTL_SECONDS:
        return list(_cache["articles"])
    try:
        timeout = aiohttp.ClientTimeout(total=FEED_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            _cache["articles"] = await _download(session)
    except Exception as exc:  # лента не должна ронять блог
        logger.warning("blog feed unavailable: %s", type(exc).__name__)
    _cache["at"] = moment
    return list(_cache["articles"])


def reset_cache() -> None:
    _cache.update(at=0.0, articles=[])


async def all_articles(builtin: tuple[dict, ...]) -> list[dict]:
    """Встроенные + платформенные статьи, новые первыми; slug встроенных не перекрывается."""
    taken = {a["slug"] for a in builtin}
    extra = [a for a in await feed_articles() if a["slug"] not in taken]
    return sorted([*builtin, *extra], key=lambda a: a["updated"], reverse=True)
