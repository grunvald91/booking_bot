"""Chromium responsive and route-flow smoke for shared ServGo login / Studio.

The built PWA is served on loopback with fixed test API responses. No production
API, provider OAuth, emails, actual companies, or user sessions are modified.
"""
from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "frontend" / "dist"
SCREENSHOTS = ROOT / "artifacts" / "login-viewports"

WIDTHS = (
    ("phone320", 320, 700),
    ("phone390", 390, 844),
    ("tablet768", 768, 950),
    ("desktop1024", 1024, 768),
    ("desktop1280", 1280, 800),
    ("desktop1440", 1440, 900),
    ("wide1920", 1920, 1080),
)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def log_message(self, *_args):
        pass

    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if route.startswith("/api/"):
            if route == "/api/auth/session":
                self.send_response(401)
                self.end_headers()
                return
            if route == "/api/auth/me":
                data = {"id": 9, "full_name": "Тестовый администратор", "role": "admin"}
            elif route == "/api/studio/businesses":
                data = [
                    {"id": 42, "name": "Тестовая компания А", "role": "owner"},
                    {"id": 43, "name": "Тестовая компания Б", "role": "owner"},
                ]
            elif route.endswith("/capabilities"):
                data = {"available": True}
            else:
                data = {}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
            return
        if route != "/" and not (DIST / route.lstrip("/")).is_file():
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/auth/phone":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"message":"code sent","fallback":false}')
            return
        self.send_response(404)
        self.end_headers()


def geometry(page, css):
    return page.locator(css).bounding_box()


def layout_assertions(page, label, width, *, studio=False):
    root = ".sg-studio-layout" if studio else ".sg-login-layout"
    left = ".sg-studio-intro" if studio else ".sg-login__brand-panel"
    right = ".sg-studio-businesses" if studio else ".sg-login"
    outer = geometry(page, root)
    panel = geometry(page, right)
    assert outer and panel, (label, root, right)
    assert outer["x"] >= 0 and outer["x"] + outer["width"] <= width + 1, (label, outer)
    assert panel["x"] >= 0 and panel["x"] + panel["width"] <= width + 1, (label, panel)
    overflow = page.evaluate("""() => {
      const offenders = [...document.querySelectorAll('*')].filter(el => {
        const style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const box = el.getBoundingClientRect();
        return box.width > 0 && (box.right > innerWidth + 1 || box.left < -1);
      }).slice(0, 18).map(el => ({
        tag: el.tagName.toLowerCase(),
        className: typeof el.className === 'string' ? el.className : '',
        x: Math.round(el.getBoundingClientRect().x),
        right: Math.round(el.getBoundingClientRect().right),
        width: Math.round(el.getBoundingClientRect().width),
      }));
      return {
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth, offenders
      };
    }""")
    assert overflow["scrollWidth"] <= width + 1, (label, "horizontal overflow", overflow)
    if studio:
        assert panel["width"] <= 460, (label, "Studio status must be compact", panel)
        assert abs(panel["x"] + panel["width"] / 2 - width / 2) <= 3, (label, "Studio status not centered", panel)
        return outer, panel
    if width >= 1024:
        brand = geometry(page, left)
        assert brand and brand["width"] >= 300, (label, brand)
        assert brand["x"] + brand["width"] + 10 <= panel["x"], (label, brand, panel)
        assert outer["width"] >= 850, (label, outer)
        assert 385 <= panel["width"] <= 560, (label, panel)
        assert page.locator(left).is_visible(), (label, "desktop brand panel hidden")
    else:
        assert page.locator(left).is_visible() == studio, (label, "tablet/mobile presentation")
        if not studio:
            assert panel["width"] <= 421, (label, panel)
    return outer, panel


def check_login(page, label, width, theme, url):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url + "/login", wait_until="domcontentloaded")
    page.get_by_role("link", name="Войти через VK ID").wait_for(timeout=12000)
    page.get_by_role("link", name="Войти через Яндекс").wait_for(timeout=12000)
    page.evaluate("(theme) => document.documentElement.dataset.theme = theme", theme)
    assert page.get_by_role("heading", name="Вход в ServGo", level=1).is_visible()
    for caption in ("Войти по email", "Войти через Telegram", "Войти по номеру телефона"):
        assert page.get_by_role("button", name=caption).is_visible(), (label, caption)
    assert page.get_by_role("link", name="Войти через VK ID").get_attribute("href") == "/api/auth/vk/start"
    assert page.get_by_role("link", name="Войти через Яндекс").get_attribute("href") == "/api/auth/yandex/start"
    outer, panel = layout_assertions(page, label, width)
    assert page.locator(".servgo-shell-header").count() == 0, (label, "duplicate public nav")
    if width < 1024:
        assert panel["y"] < 150, (label, "mobile login must start near header", panel)

    rows = page.locator(".sg-login__provider, .sg-login__method").all()
    assert len(rows) == 5, (label, len(rows))
    min_height = 46 if width >= 1024 else 40
    for row in rows:
        rect = row.bounding_box()
        assert rect and rect["height"] >= min_height, (label, "short auth action", rect)
        assert rect["x"] >= panel["x"] - 1 and rect["x"] + rect["width"] <= panel["x"] + panel["width"] + 1
    if width >= 1024:
        font_size = page.locator(".sg-login__method").first.evaluate(
            "(el) => parseFloat(getComputedStyle(el).fontSize)")
        assert font_size >= 14, (label, font_size)
        assert panel["width"] >= 385, (label, "desktop form too narrow", panel)

    page.screenshot(path=str(SCREENSHOTS / f"{label}-{theme}-closed.png"), full_page=True)
    if not page.get_by_label("Email", exact=True).is_visible():
        page.get_by_role("button", name="Войти по email").click()
    assert page.get_by_label("Email", exact=True).is_visible()
    assert page.get_by_label("Пароль", exact=True).is_visible()
    page.screenshot(path=str(SCREENSHOTS / f"{label}-{theme}-email.png"), full_page=True)
    page.get_by_role("button", name="Войти через Telegram").click()
    assert page.locator(".sg-login__telegram-widget").count() == 1
    assert not page.locator("#sg-login-email").is_visible()
    page.get_by_role("button", name="Войти по номеру телефона").click()
    assert page.get_by_label("Номер телефона").is_visible()
    page.get_by_label("Номер телефона").fill("+79000000000")
    page.get_by_role("button", name="Получить код").click()
    page.get_by_label("Цифра кода 6").wait_for(timeout=8000)
    assert page.locator(".sg-login__code-fields input").count() == 6
    contrast = page.evaluate("""() => ({
      panel: getComputedStyle(document.querySelector('.sg-login__phone')).backgroundColor,
      digit: getComputedStyle(document.querySelector('.sg-login__code-fields input:nth-child(2)')).backgroundColor,
    })""")
    assert contrast["panel"] != contrast["digit"], (label, theme, contrast)
    code = geometry(page, ".sg-login__code-fields")
    assert code and code["x"] >= panel["x"] and code["x"] + code["width"] <= panel["x"] + panel["width"] + 1
    page.screenshot(path=str(SCREENSHOTS / f"{label}-{theme}-phone-code.png"), full_page=True)
    assert not errors, (label, errors)
    print("AUTH_RESPONSIVE_OK", json.dumps({
        "viewport": label, "theme": theme, "layout_width": round(outer["width"]),
        "form_width": round(panel["width"]), "providers": len(rows),
    }, ensure_ascii=False), flush=True)


def check_studio(browser, url, label, width, height, theme):
    context = browser.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce")
    context.add_init_script("""
        localStorage.setItem('token', 'servgo-browser-only-fixture');
        localStorage.setItem('userRole', 'admin');
        localStorage.setItem('userName', 'Тестовый администратор');
    """)
    page = context.new_page()
    requests = []
    booking_requests = []
    def ticket(route):
        requests.append(route.request.method)
        if len(requests) == 1:
            route.fulfill(status=503, content_type="application/json", body='{"detail":"fixture outage"}')
        else:
            route.fulfill(status=200, content_type="application/json",
                          body='{"url":"https://servgo.ru/studio/sso?t=fixture.ticket","expires_in":60}')
    def booking(route):
        booking_requests.append(route.request.url)
        route.abort()
    page.route("**/api/studio/account-ticket", ticket)
    page.route("**/api/studio/businesses", booking)
    # Never navigate to production: the expected canonical SSO handoff is a
    # local Playwright response. The actual backend is tested separately.
    page.route("https://servgo.ru/studio/sso?*", lambda route: route.fulfill(
        status=200, content_type="text/html", body="<h1>Fixture Studio reached</h1>"))
    page.goto(url + "/workspace/studio-entry", wait_until="domcontentloaded")
    page.get_by_role("button", name="Повторить вход").wait_for(timeout=14000)
    page.evaluate("(theme) => document.documentElement.dataset.theme = theme", theme)
    assert page.get_by_role("heading", name="Студия ServGo", level=1).is_visible()
    assert page.get_by_role("link", name="Мой аккаунт").is_visible()
    outer, panel = layout_assertions(page, label, width, studio=True)
    assert page.locator(".servgo-shell-header").count() == 0, (label, "duplicate Studio nav")
    page.screenshot(path=str(SCREENSHOTS / f"{label}-{theme}-studio.png"), full_page=True)
    page.get_by_role("button", name="Повторить вход").click()
    page.get_by_role("heading", name="Fixture Studio reached").wait_for(timeout=12000)
    assert page.url == "https://servgo.ru/studio/sso?t=fixture.ticket"
    assert requests == ["POST", "POST"], (label, requests)
    assert not booking_requests, (label, booking_requests)
    print("STUDIO_RESPONSIVE_OK", json.dumps({
        "viewport": label, "theme": theme, "layout_width": round(outer["width"]),
        "panel_width": round(panel["width"]), "account_handoff": True,
    }, ensure_ascii=False), flush=True)
    context.close()


def main():
    if not (DIST / "index.html").is_file():
        raise RuntimeError("Build web/frontend/dist first")
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for label, width, height in WIDTHS:
                for theme in ("light", "dark"):
                    context = browser.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce")
                    page = context.new_page()
                    page.route("https://tg.servgo.ru/**", lambda route: route.abort())
                    page.route("https://telegram.org/**", lambda route: route.abort())
                    check_login(page, label, width, theme, url)
                    context.close()
                    check_studio(browser, url, label, width, height, theme)
            context = browser.new_context(viewport={"width": 390, "height": 844})
            page = context.new_page()
            page.route("**/api/auth/vk/capabilities", lambda route: route.fulfill(
                status=200, content_type="application/json", body='{"available":false}'))
            page.route("**/api/auth/yandex/capabilities", lambda route: route.fulfill(
                status=200, content_type="application/json", body='{"available":false}'))
            page.goto(url + "/login", wait_until="domcontentloaded")
            page.get_by_text("VK ID — пока недоступен").wait_for(timeout=10000)
            page.get_by_text("Яндекс — пока недоступен").wait_for(timeout=10000)
            assert page.get_by_role("button", name="Войти по email").is_visible()
            print("AUTH_UNAVAILABLE_PROVIDER_FALLBACK_OK", flush=True)
            context.close()

            # A Studio deep link must use the same login page and all five providers.
            guest = browser.new_context(viewport={"width": 1280, "height": 800})
            page = guest.new_page()
            page.goto(url + "/workspace/studio-entry", wait_until="domcontentloaded")
            page.get_by_role("heading", name="Вход в ServGo", level=1).wait_for(timeout=12000)
            assert page.get_by_text("После входа откроется Студия", exact=False).is_visible()
            assert page.get_by_role("link", name="Войти через VK ID").is_visible()
            assert "/login?next=" in page.url, page.url
            print("STUDIO_CANONICAL_LOGIN_REDIRECT_OK", flush=True)
            guest.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
