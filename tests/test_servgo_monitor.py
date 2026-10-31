import asyncio
import json
import threading
import time

import ops.servgo_monitor as monitor

"""Deterministic alert-state tests; no Telegram traffic."""
from ops.servgo_monitor import update_states, mark_delivered, message, healthy_http_code, healthy_docker_state


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


def test_growth_worker_and_container_health_are_monitored():
    assert healthy_docker_state("true|healthy", True)
    assert healthy_docker_state("true|", True)  # Containers without HEALTHCHECK.
    assert not healthy_docker_state("true|unhealthy", True)
    assert not healthy_docker_state("true|starting", True)
    assert not healthy_docker_state("false|", True)
    assert not healthy_docker_state("true|healthy", False)


def test_recovery_does_not_send_during_one_failed_flapping_probe():
    key = "https:promo.servgo.ru"
    state = {"checks": {}}
    for when in (100, 110):
        state, pending = update_states(state, {key: (False, "HTTP 502")}, now=when)
    mark_delivered(state, "down", [key], now=110)
    for when in (120, 130):
        state, pending = update_states(state, {key: (True, "HTTP 200")}, now=when)
    assert pending["up"] == [(key, "HTTP 200")]
    state, pending = update_states(state, {key: (False, "HTTP 502")}, now=140)
    assert pending["up"] == []
    state, pending = update_states(state, {key: (True, "HTTP 200")}, now=150)
    assert pending["up"] == []
    state, pending = update_states(state, {key: (True, "HTTP 200")}, now=160)
    assert pending["up"] == [(key, "HTTP 200")]


def test_alert_batches_cover_every_incident_without_truncation():
    incidents = [(f"service:example-{i}.service", "not responding " + "x" * 142)
                 for i in range(60)]
    batches = monitor.alert_batches("down", incidents)
    assert len(batches) > 2
    assert [item for items, _ in batches for item in items] == incidents
    assert all(len(text) <= 3500 for _, text in batches)
    assert all(len(text) <= 3800 for _, text in batches)


def test_monitors_really_probe_concurrently(monkeypatch):
    active = [0]
    max_active = [0]
    lock = threading.Lock()

    def sample(*_args):
        with lock:
            active[0] += 1
            max_active[0] = max(max_active[0], active[0])
        time.sleep(0.03)
        with lock:
            active[0] -= 1
        return True, "ok"

    for name in ("_service_check", "_docker_check", "_site_check", "_telegram_proxy_check",
                 "_local_web_check", "_disk_check", "_tls_check"):
        monkeypatch.setattr(monitor, name, sample)
    observations = monitor.collect_checks()
    assert len(observations) == 36
    assert all(ok for ok, _ in observations.values())
    assert max_active[0] > 1


def test_partial_batch_delivery_only_acknowledges_delivered_incidents(tmp_path, monkeypatch):
    incidents = {f"service:example-{i}": (False, "failed " + "x" * 144)
                 for i in range(60)}
    monitor_path = tmp_path / "monitor.json"
    monkeypatch.setattr(monitor, "STATE_PATH", monitor_path)
    monkeypatch.setattr(monitor, "collect_checks", lambda: incidents)
    seen = []

    async def unreliable_send(text):
        seen.append(text)
        return len(seen) == 1

    monkeypatch.setattr(monitor, "send_message", unreliable_send)
    assert asyncio.run(monitor.run())
    # First sample: not yet confirmed, no alerts should be sent.
    assert seen == []
    assert not asyncio.run(monitor.run())
    assert len(seen) > 1
    saved = json.loads(monitor_path.read_text())
    acked = [key for key, item in saved["checks"].items() if item["notified"]]
    pending = [key for key, item in saved["checks"].items()
               if item["pending"] == "down" and not item["notified"]]
    assert acked and pending
    assert len(acked) + len(pending) == len(incidents)


def test_disk_full_still_alerts_even_when_incident_state_cannot_be_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "STATE_PATH", tmp_path / "monitor.json")
    monkeypatch.setattr(monitor, "collect_checks", lambda: {
        "disk:root": (False, "disk 100% used"),
        "https:promo.servgo.ru": (True, "HTTP 200"),
    })

    def cant_save(_state):
        raise OSError("no space left")

    delivered = []
    async def send(text):
        delivered.append(text)
        return True

    monkeypatch.setattr(monitor, "save_state", cant_save)
    monkeypatch.setattr(monitor, "send_message", send)
    assert not asyncio.run(monitor.run())
    assert len(delivered) == 1
    assert "disk:root" in delivered[0]
    assert "disk 100% used" in delivered[0]
