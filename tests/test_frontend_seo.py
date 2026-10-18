"""Регрессия SEO фронтенда servgo.ru: верификация Яндекса, robots.txt, sitemap.xml."""
from pathlib import Path
import xml.etree.ElementTree as ET

FRONT = Path(__file__).resolve().parents[1] / "web" / "frontend"


def test_index_has_yandex_verification_and_meta():
    html = (FRONT / "index.html").read_text(encoding="utf-8")
    assert '<meta name="yandex-verification" content="24c86f64d4a09338" />' in html
    assert '<meta name="description"' in html
    assert 'og:image" content="https://servgo.ru/og-image.png"' in html
    # Общий canonical на главную склеил бы страницы бизнесов с главной — его ставит JS по маршруту.
    assert 'rel="canonical"' not in html


def test_robots_blocks_private_but_not_api():
    robots = (FRONT / "public" / "robots.txt").read_text(encoding="utf-8").splitlines()
    disallow = {line.split(":", 1)[1].strip() for line in robots if line.startswith("Disallow:")}
    for private in ("/admin", "/account", "/login", "/b/", "/rental/b/", "/book"):
        assert private in disallow
    # Страницы бизнесов грузят данные из /api/ — без доступа поисковик увидит пустую страницу.
    assert not any(d.startswith("/api") for d in disallow)
    assert not any("/business".startswith(d) for d in disallow if d != "/")
    assert "Sitemap: https://servgo.ru/sitemap.xml" in robots


def test_sitemap_is_valid_and_points_to_servgo():
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.parse(FRONT / "public" / "sitemap.xml").getroot()
    locs = [el.text for el in root.findall("s:url/s:loc", ns)]
    assert "https://servgo.ru/" in locs
    assert all(loc.startswith("https://servgo.ru/") for loc in locs)


def test_og_image_is_1200x630_png():
    data = (FRONT / "public" / "og-image.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    assert (width, height) == (1200, 630)
