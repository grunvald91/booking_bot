"""Real Chromium responsive smoke for the shared ServGo/Studio login.

Uses the built PWA in an isolated loopback fixture. Never calls production APIs
or creates a live account. Saves viewport screenshots for manual UX review.
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
            data = {"available": True} if route.endswith("/capabilities") else {}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
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


def check_page(page, label, theme):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(page.context._sg_url + "/login", wait_until="domcontentloaded")
    page.get_by_role("link", name="Войти через VK ID").wait_for(timeout=12000)
    page.get_by_role("link", name="Войти через Яндекс").wait_for(timeout=12000)
    page.evaluate("(theme) => document.documentElement.dataset.theme = theme", theme)

    for label_text in ("Войти по email", "Войти через Telegram", "Войти по номеру телефона"):
        assert page.get_by_role("button", name=label_text).is_visible(), (label, label_text)

    rect = page.locator(".sg-login").bounding_box()
    assert rect and rect["width"] <= 421, (label, rect)
    assert rect["x"] >= 0 and rect["x"] + rect["width"] <= page.viewport_size["width"] + 1, (label, rect)
    actual = page.evaluate("""() => {
      const root = document.querySelector('.sg-login');
      return {overflow: document.documentElement.scrollWidth > innerWidth + 1,
              root: root.getBoundingClientRect().toJSON(),
              rows: [...root.querySelectorAll('.sg-login__provider,.sg-login__method')]
                 .map(e => ({width:e.getBoundingClientRect().width,
                             left:e.getBoundingClientRect().left,
                             right:e.getBoundingClientRect().right}))};
    }""")
    assert not actual["overflow"], (label, actual)
    assert all(0 <= row["left"] and row["right"] <= page.viewport_size["width"] + 1
               for row in actual["rows"]), (label, actual)

    page.screenshot(path=str(SCREENSHOTS / f"{label}-{theme}-closed.png"), full_page=True)
    page.get_by_role("button", name="Войти по email").click()
    assert page.get_by_label("Email", exact=True).is_visible()
    assert page.get_by_label("Пароль", exact=True).is_visible()
    assert page.locator("#sg-login-email").is_visible()
    page.screenshot(path=str(SCREENSHOTS / f"{label}-{theme}-email.png"), full_page=True)

    page.get_by_role("button", name="Войти через Telegram").click()
    assert page.locator("#sg-login-telegram").is_visible()
    assert page.locator(".sg-login__telegram-widget").count() == 1
    assert not page.locator("#sg-login-email").is_visible()

    page.get_by_role("button", name="Войти по номеру телефона").click()
    assert page.locator("#sg-login-phone").is_visible()
    assert page.get_by_label("Номер телефона").is_visible()
    page.get_by_label("Номер телефона").fill("+79000000000")
    page.get_by_role("button", name="Получить код").click()
    page.get_by_label("Цифра кода 6").wait_for(timeout=8000)
    code = page.locator(".sg-login__code-fields").bounding_box()
    assert code and code["x"] >= 0 and code["x"] + code["width"] <= page.viewport_size["width"] + 1, (label, code)
    page.screenshot(path=str(SCREENSHOTS / f"{label}-{theme}-phone-code.png"), full_page=True)
    assert not errors, (label, errors)
    print("AUTH_VIEWPORT_OK", json.dumps({"viewport": label, "theme": theme,
        "width": rect["width"], "rows": len(actual["rows"]), "phone_code_width": code["width"]},
        ensure_ascii=False), flush=True)


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
            for label, width, height in (("phone320", 320, 700), ("phone390", 390, 844), ("desktop", 1440, 900)):
                for theme in ("light", "dark"):
                    context = browser.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce")
                    # Local fixture URL; not persisted in Chromium storage.
                    context._sg_url = url
                    page = context.new_page()
                    page.route("https://tg.servgo.ru/**", lambda route: route.abort())
                    page.route("https://telegram.org/**", lambda route: route.abort())
                    check_page(page, label, theme)
                    context.close()
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
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
