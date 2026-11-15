"""Contract tests for the narrow, reversible ServGo public SEO nginx routing."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/ops/servgo_company_blog_nginx_release.py"
spec = spec_from_file_location("company_seo_nginx_release", PATH)
release = module_from_spec(spec)
spec.loader.exec_module(release)


def test_company_blog_location_catches_articles_sitemaps_and_invalid_paths():
    location = next(line.strip() for line in release.SNIPPET.splitlines()
                    if line.strip().startswith("location ~ ^/business/") and "(?:/|$)" in line)
    pattern = location.split("location ~ ", 1)[1].split(" {", 1)[0]
    for path in (
        "/business/1/blog", "/business/64/blog/",
        "/business/64/blog/sitemap.xml",
        "/business/64/blog/kak-uhazhivat-za-volosami",
        "/business/64/blog/__invalid_slug__",
    ):
        assert re.search(pattern, path), path
    for path in ("/business/64", "/business/64/blogger", "/blog/article", "/business/abc/blog"):
        assert not re.search(pattern, path), path


def test_only_public_company_blog_route_changes():
    assert release.SNIPPET.count("rewrite ") == 1
    assert "/api/seo-pages/business/$1/blog$2 last;" in release.SNIPPET
    assert "limit_except GET HEAD { deny all; }" in release.SNIPPET
    assert "SERVGO_COMPANY_SEO_SSR_BEGIN" in release.SNIPPET
    assert "location = /blog" in release.ANCHOR
    assert "proxy_pass" not in release.SNIPPET
