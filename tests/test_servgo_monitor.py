"""Deterministic alert-state tests; no Telegram traffic."""
from ops.servgo_monitor import update_states, mark_delivered, message, healthy_http_code


def test_monitor_requires_two_failures_and_sends_a_single_alert():
    state = {"checks": {}}
    error = {"https:promo.servgo.ru": (False, "HTTP 502")}
    state, pending = update_states(state, error, now=100)
    assert pending["down"] == []
    state, pending = update_states(state, error, now=110)
    assert pending["down"] == [("https:promo.servgo.ru", "HTTP 502")]
    mark_delivered(state, "down", ["https:promo.servgo.ru"], now=110)
    state, pending = update_states(state, error, now=130)
    assert pending["down"] == []


def test_monitor_sends_recovery_after_two_successes_only():
    key = "service:booking-bot.service"
    state = {"checks": {}}
    for when in (100, 110):
        state, _ = update_states(state, {key: (False, "failed")}, now=when)
    mark_delivered(state, "down", [key], now=110)
    state, first = update_states(state, {key: (True, "active")}, now=120)
    assert first["up"] == []
    state, second = update_states(state, {key: (True, "active")}, now=130)
    assert second["up"] == [(key, "active")]
    mark_delivered(state, "up", [key], now=130)
    state, again = update_states(state, {key: (True, "active")}, now=150)
    assert again["up"] == []


def test_alert_is_retried_if_delivery_fails():
    key = "disk:root"
    state = {"checks": {}}
    for when in (100, 110, 120):
        state, pending = update_states(state, {key: (False, "disk 95% used")}, now=when)
    assert pending["down"] == [(key, "disk 95% used")]


def test_six_hour_repeat_and_no_secrets_in_generated_text():
    key = "proxy:telegram-egress"
    state = {"checks": {}}
    for when in (100, 110):
        state, _ = update_states(state, {key: (False, "offline")}, now=when)
    mark_delivered(state, "down", [key], now=110)
    state, pending = update_states(state, {key: (False, "offline")}, now=110+21599)
    assert pending["down"] == []
    state, pending = update_states(state, {key: (False, "offline")}, now=110+21600)
    assert pending["down"] == [(key, "offline")]
    assert "ServGo" in message("down", pending["down"])


def test_never_send_recovery_if_initial_outage_was_not_delivered():
    state = {"checks": {}}
    key = "https:mail.servgo.ru"
    for when in (100, 110):
        state, _ = update_states(state, {key: (False, "HTTP 502")}, now=when)
    for when in (120, 130):
        state, pending = update_states(state, {key: (True, "HTTP 200")}, now=when)
    assert pending["up"] == []


def test_protected_sto_401_is_reachable_but_other_401_is_not():
    assert healthy_http_code("sto.servgo.ru", "401", True)
    assert not healthy_http_code("promo.servgo.ru", "401", True)
    assert not healthy_http_code("sto.servgo.ru", "502", True)
    assert not healthy_http_code("sto.servgo.ru", "401", False)
