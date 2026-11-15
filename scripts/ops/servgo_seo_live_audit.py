#!/usr/bin/env python3
"""Read-only SEO smoke test executed on the ServGo host over pinned SSH.

No application/DB/nginx writes, no credentials printed. HTTPS is resolved
locally so this checks the production virtual host, not external DNS.
"""
from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

ROOT = "https://servgo.ru"
errors: list[str] = []


def request(path: str) -> tuple[int, str]:
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("Unsafe path")
    proc = subprocess.run(
        ["curl", "-ksS", "--max-time", "15",
         "--resolve", "servgo.ru:443:127.0.0.1",
         "-w", "\\n__HTTP_STATUS__=%{http_code}", ROOT + path],
        capture_output=True, text=True, timeout=20, check=False,
    )
    if proc.returncode != 0 or "__HTTP_STATUS__=" not in proc.stdout:
        errors.append(f"{path}: curl failed ({proc.returncode})")
        return 0, ""
    body, status = proc.stdout.rsplit("\n__HTTP_STATUS__=", 1)
    try:
        code = int(status.strip())
    except ValueError:
        errors.append(f"{path}: invalid HTTP status")
        return 0, body
    print(f"{path} HTTP={code} bytes={len(body.encode('utf-8'))}", flush=True)
    return code, body


def require(condition: bool, issue: str) -> None:
    if not condition:
        errors.append(issue)


def xml_locs(path: str, *, expect_index: bool = False) -> list[str]:
    status, body = request(path)
    require(status == 200, f"{path}: expected HTTP 200")
    if status != 200:
        return []
    try:
        tree = ET.fromstring(body)
    except ET.ParseError:
        errors.append(f"{path}: invalid XML")
        return []
    locals_ = [
        (e.text or "").strip()
        for e in tree.iter()
        if e.tag.endswith("}loc") or e.tag == "loc"
    ]
    require(tree.tag.endswith("sitemapindex") if expect_index else tree.tag.endswith("urlset"),
            f"{path}: unexpected sitemap root {tree.tag}")
    require(all(x.startswith(ROOT + "/") for x in locals_), f"{path}: foreign/non-HTTPS URL in sitemap")
    print(f"{path} entries={len(locals_)}", flush=True)
    return locals_


def canonical(html: str) -> str | None:
    tag = re.search(r'<link\b[^>]*\brel=["\']canonical["\'][^>]*>', html, re.I)
    if not tag:
        return None
    href = re.search(r'\bhref=["\']([^"\']+)["\']', tag.group(), re.I)
    return href.group(1) if href else None


def inspect_html(path: str, *, expected: str, require_ssr: bool = False) -> None:
    status, body = request(path)
    require(status == 200, f"{path}: expected HTTP 200")
    if status != 200:
        return
    actual = canonical(body)
    if actual:
        require(actual == expected, f"{path}: canonical {actual!r}, expected {expected!r}")
        print(f"{path} canonical={actual}", flush=True)
    elif not require_ssr:
        require('id="seo-route-bootstrap"' in body and "canonical.href = 'https://servgo.ru' + canonicalPath" in body,
                f"{path}: expected route-aware SEO bootstrap in SPA HTML")
        print(f"{path} route_canonical_bootstrap={'seo-route-bootstrap' in body}", flush=True)
    else:
        errors.append(f"{path}: missing server-rendered canonical")
    require("noindex" not in re.sub(r"<script.*?</script>", "", body, flags=re.S | re.I).lower(),
            f"{path}: noindex in original HTML outside scripts")


def main() -> int:
    inspect_html("/", expected=ROOT + "/")
    robots_status, robots = request("/robots.txt")
    require(robots_status == 200, "robots.txt: expected 200")
    require("Sitemap: https://servgo.ru/sitemap.xml" in robots,
            "robots.txt: primary sitemap not advertised")

    locs = xml_locs("/sitemap.xml")
    company_paths = []
    for url in locs:
        path = urlsplit(url).path
        if re.fullmatch(r"/business/[1-9][0-9]*", path):
            company_paths.append(path)
    for path in company_paths[:3]:
        inspect_html(path, expected=ROOT + path)

    inspect_html("/blog", expected=ROOT + "/blog", require_ssr=True)
    blog_locs = xml_locs("/blog/sitemap.xml")
    article_paths = []
    for url in blog_locs:
        path = urlsplit(url).path
        if re.fullmatch(r"/blog/[a-z0-9-]+", path):
            article_paths.append(path)
    for path in article_paths[:3]:
        inspect_html(path, expected=ROOT + path, require_ssr=True)

    # Company blog index is advertised by robots.txt; it must be served as XML.
    company_index_status, company_index = request("/business-blog-sitemap.xml")
    if company_index_status != 200:
        errors.append("/business-blog-sitemap.xml: advertised sitemap not HTTP 200")
    else:
        try:
            root = ET.fromstring(company_index)
            require(root.tag.endswith("sitemapindex"), "Company sitemap is not sitemapindex XML")
        except ET.ParseError:
            errors.append("Company sitemap invalid XML")

    print(f"seo_audit_ok={str(not errors).lower()} company_samples={min(len(company_paths), 3)} "
          f"article_samples={min(len(article_paths), 3)}")
    for error in errors:
        print("SEO_ERROR=" + error)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
