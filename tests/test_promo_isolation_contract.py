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
