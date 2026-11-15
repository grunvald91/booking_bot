#!/usr/bin/env python3
"""Генерация sitemap.xml для servgo.ru из живого списка бизнесов.

Запускается на сервере по cron (см. .github/workflows/servgo-sitemap-install.yml):
берёт активные бизнесы из локального API и атомарно перезаписывает
web/frontend/dist/sitemap.xml, который nginx отдаёт как статику.

Только стандартная библиотека — запускается системным python3.
Если API недоступен или ответ странный, существующий sitemap не трогаем.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from xml.sax.saxutils import escape

SITE_URL = "https://servgo.ru"
DEFAULT_API_URL = "http://127.0.0.1:8000/businesses"
DEFAULT_OUT = "/opt/booking_bot/web/frontend/dist/sitemap.xml"
DEFAULT_COMPANY_API_URL = "http://127.0.0.1:8000/seo-pages/sitemap.xml"
SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"


def fetch_business_ids(api_url: str, timeout: float = 15.0) -> list[int]:
    with urllib.request.urlopen(api_url, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("API returned non-list payload")
    ids = sorted({int(item["id"]) for item in data if isinstance(item, dict) and str(item.get("id", "")).isdigit()})
    return ids


def fetch_company_blog_sitemap(api_url: str, timeout: float = 15.0) -> str:
    """Copy only the validated public company sitemap index from the local API."""
    with urllib.request.urlopen(api_url, timeout=timeout) as resp:
        content = resp.read(1_000_001)
    if len(content) > 1_000_000:
        raise ValueError("Company sitemap index exceeds safety limit")
    xml = content.decode("utf-8")
    root = ET.fromstring(xml)
    if root.tag != f"{{{SITEMAP_NAMESPACE}}}sitemapindex":
        raise ValueError("Company sitemap source is not sitemapindex XML")
    for sitemap in root:
        if sitemap.tag != f"{{{SITEMAP_NAMESPACE}}}sitemap":
            raise ValueError("Unexpected company sitemap element")
        loc = sitemap.find(f"{{{SITEMAP_NAMESPACE}}}loc")
        if loc is None or not isinstance(loc.text, str):
            raise ValueError("Company sitemap entry missing URL")
        if not re.fullmatch(r"https://servgo\.ru/business/[1-9][0-9]*/blog/sitemap\.xml", loc.text.strip()):
            raise ValueError("Company sitemap has an unexpected URL")
    return xml


def build_sitemap(business_ids: list[int], today: str) -> str:
    rows = [(f"{SITE_URL}/", "daily", "1.0")]
    rows += [(f"{SITE_URL}/business/{bid}", "weekly", "0.8") for bid in business_ids]
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, freq, prio in rows:
        parts.append(
            f"  <url><loc>{escape(loc)}</loc><lastmod>{today}</lastmod>"
            f"<changefreq>{freq}</changefreq><priority>{prio}</priority></url>"
        )
    parts.append("</urlset>")
    return "\n".join(parts) + "\n"


def write_atomic(path: str, content: str) -> None:
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".sitemap.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--with-company", action="store_true",
                        help="Also generate business-blog-sitemap.xml next to --out")
    parser.add_argument("--company-api-url", default=DEFAULT_COMPANY_API_URL)
    args = parser.parse_args(argv)

    stamp = datetime.now(timezone.utc)
    try:
        ids = fetch_business_ids(args.api_url)
        company_xml = (fetch_company_blog_sitemap(args.company_api_url)
                       if args.with_company else None)
    except Exception as exc:  # noqa: BLE001 — сохраняем ранее работавшие файлы
        print(f"{stamp:%Y-%m-%dT%H:%M:%SZ} sitemap: API error, keeping previous files: {exc}", file=sys.stderr)
        return 1
    try:
        write_atomic(args.out, build_sitemap(ids, stamp.strftime("%Y-%m-%d")))
        if company_xml is not None:
            company_out = os.path.join(os.path.dirname(args.out), "business-blog-sitemap.xml")
            write_atomic(company_out, company_xml)
            print(f"{stamp:%Y-%m-%dT%H:%M:%SZ} company sitemap: written to {company_out}")
    except OSError as exc:
        print(f"{stamp:%Y-%m-%dT%H:%M:%SZ} sitemap: write failed: {exc}", file=sys.stderr)
        return 1
    print(f"{stamp:%Y-%m-%dT%H:%M:%SZ} sitemap: written {len(ids) + 1} urls to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
