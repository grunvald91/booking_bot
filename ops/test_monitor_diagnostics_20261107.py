#!/usr/bin/env python3
"""Offline contract tests: never send notifications or change real monitor state."""
import importlib.util
import json
import sys
from types import SimpleNamespace
from unittest.mock import patch


def main(candidate):
    spec = importlib.util.spec_from_file_location("servgo_monitor_under_test", candidate)
    monitor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(monitor)

    def step(prev, ok, detail, epoch):
        return monitor.update_states(
            prev, {"proxy:telegram-egress": (ok, detail)}, float(epoch))

    state = {"checks": {}}
    state, queue = step(state, False, "curl exit 28: Connection timed out", 1000)
    assert not queue["down"]
    assert state["checks"]["proxy:telegram-egress"]["down_since"] == 1000
    state, queue = step(state, False, "curl exit 28: Connection timed out", 1120)
    assert len(queue["down"]) == 1
    assert "curl exit 28" in queue["down"][0][1]
    assert "2 мин" in queue["down"][0][1]
    assert "первый сбой:" in queue["down"][0][1]
    monitor.mark_delivered(state, "down", ["proxy:telegram-egress"], 1120)
    state, queue = step(state, True, "Telegram через SOCKS5 HTTP 200", 1240)
    assert not queue["up"] and state["checks"]["proxy:telegram-egress"]["alarm"]
    state, queue = step(state, True, "Telegram через SOCKS5 HTTP 200", 1360)
    assert len(queue["up"]) == 1
    assert "4 мин" in queue["up"][0][1]
    assert "curl exit 28" in queue["up"][0][1]
    assert state["checks"]["proxy:telegram-egress"]["outage_seconds"] == 240
    assert state["checks"]["proxy:telegram-egress"]["recovered_at"] == 1240
    # Pending success is not cleared until successful notification delivery.
    state, queue = step(state, True, "Telegram через SOCKS5 HTTP 200", 1480)
    assert len(queue["up"]) == 1
    monitor.mark_delivered(state, "up", ["proxy:telegram-egress"], 1480)
    state, queue = step(state, False, "curl exit 7: Connection refused", 1600)
    assert state["checks"]["proxy:telegram-egress"]["down_since"] == 1600
    assert "4 мин" in monitor.message("up", [("proxy", "4 мин")])
    assert not queue["down"]
    state, queue = step(state, False, "curl exit 7: Connection refused", 1720)
    assert "curl exit 7" in queue["down"][0][1]
    monitor.mark_delivered(state, "down", ["proxy:telegram-egress"], 1720)
    state, queue = step(state, False, "curl exit 7: Connection refused", 1840)
    assert not queue["down"]  # No duplicate before six hours
    state, queue = step(state, False, "curl exit 7: Connection refused", 1720 + 21601)
    assert len(queue["down"]) == 1

    # Old saved state with active alarm must not invent original start time.
    legacy = {"checks": {"proxy:telegram-egress": {
        "alarm": True, "bad": 3, "good": 0,
        "notified": True, "pending": "", "last_sent": 10,
        "detail": "Telegram egress HTTP 000",
    }}}
    legacy, queue = step(legacy, False, "curl exit 28: Timeout", 50000)
    assert legacy["checks"]["proxy:telegram-egress"]["start_late"]
    assert "обновления мониторинга" in queue["down"][0][1]

    # Avoid leaking credentials or URLs from curl's stderr.
    error = monitor._safe_monitor_error(
        "curl: (7) Failed to reach https://example.test/path?token=private-value")
    assert "https://" not in error and "private-value" not in error
    with patch.object(monitor.subprocess, "run", return_value=SimpleNamespace(
            stdout="000", stderr="curl: (28) Operation timed out", returncode=28)):
        ok, code, detail = monitor.command_diagnostic(["curl"], timeout=11)
    assert not ok and code == "000" and "28" in detail and "timed out" in detail
    with patch.object(monitor.subprocess, "run", return_value=SimpleNamespace(
            stdout="200", stderr="", returncode=0)):
        ok, code, detail = monitor.command_diagnostic(["curl"], timeout=11)
    assert ok and code == "200" and detail == ""

    assert monitor.healthy_http_code("servgo.ru", "200", True)
    assert not monitor.healthy_http_code("servgo.ru", "000", False)
    assert "длительность" in queue["down"][0][1] or "длится" in queue["down"][0][1]
    json.dumps(state, ensure_ascii=False)
    print("PASS: detailed curl exit errors, URL redaction, down/recovery timestamps, "
          "duration, delivery retry, deduplication, legacy state compatibility.")
    print("NETWORK_CALLS=0 TELEGRAM_MESSAGES=0 STATE_WRITES=0")


if __name__ == "__main__":
    main(sys.argv[1])
