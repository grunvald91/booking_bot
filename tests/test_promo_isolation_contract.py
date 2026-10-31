import asyncio
import importlib.util
import sys
import types

import aiohttp
from aiohttp import web
import pytest

"""Contract checks: promo has a dedicated runner without Telegram polling."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_promo_entrypoint_reuses_existing_routes_without_starting_bot():
    source = (ROOT / "webapp/promo_standalone.py").read_text()
    tree = ast.parse(source)
    assert "create_webapp()" in source
    assert '"/_promo_health"' in source
    assert "start_polling" not in source
    assert "ReminderScheduler" not in source
    assert '"127.0.0.1"' in source
    assert '"18080"' in source
    assert any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in tree.body)


def test_service_is_independent_of_booking_bot_and_telegram_proxy():
    service = (ROOT / "deploy/systemd/servgo-promo-web.service").read_text()
    assert "webapp.promo_standalone" in service
    assert "PROMO_WEBAPP_PORT=18080" in service
    assert "Requires=booking-bot" not in service
    assert "After=booking-bot" not in service
    assert "BOT_PROXY_URL" not in service
    assert "WantedBy=multi-user.target" in service


def _load_standalone_with_stub_server(monkeypatch):
    """Import just the isolated entrypoint, not Telegram or database internals."""
    webapp_pkg = types.ModuleType("webapp")
    webapp_pkg.__path__ = []
    fake_server = types.ModuleType("webapp.server")

    async def niche(_request):
        return web.Response(text="niche")

    def stub_webapp():
        app = web.Application()
        app.router.add_get("/{slug:[a-z][a-z0-9-]*}", niche)
        return app

    fake_server.create_webapp = stub_webapp
    monkeypatch.setitem(sys.modules, "webapp", webapp_pkg)
    monkeypatch.setitem(sys.modules, "webapp.server", fake_server)
    spec = importlib.util.spec_from_file_location(
        "servgo_isolated_promo_test", ROOT / "webapp/promo_standalone.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_promo_health_route_is_served_after_niche_catchall(monkeypatch):
    module = _load_standalone_with_stub_server(monkeypatch)

    async def probe():
        runner = web.AppRunner(module.make_app())
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        try:
            port = site._server.sockets[0].getsockname()[1]
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://127.0.0.1:{port}/_promo_health") as r:
                    assert r.status == 200
                    assert await r.text() == "ok"
                    assert r.headers["Cache-Control"] == "no-store"
                async with session.get(f"http://127.0.0.1:{port}/beauty") as r:
                    assert r.status == 200
                    assert await r.text() == "niche"
        finally:
            await runner.cleanup()

    asyncio.run(probe())


def test_promo_entrypoint_rejects_public_bind_and_reserved_ports(monkeypatch):
    module = _load_standalone_with_stub_server(monkeypatch)
    monkeypatch.setenv("PROMO_WEBAPP_HOST", "0.0.0.0")
    with pytest.raises(RuntimeError):
        module.main()
    monkeypatch.setenv("PROMO_WEBAPP_HOST", "127.0.0.1")
    monkeypatch.setenv("PROMO_WEBAPP_PORT", "80")
    with pytest.raises(ValueError):
        module.main()
