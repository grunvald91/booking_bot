"""ServGo independent health monitor: services, HTTP, proxy, TLS and disk.

Runs as a short-lived systemd timer, not as part of the booking Telegram bot.
Only status metadata is sent; no credentials, customer records or logs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

STATE_PATH = Path(os.environ.get("SERVGO_MONITOR_STATE", "/var/lib/servgo-monitor/state.json"))
FAIL_THRESHOLD = 2
RECOVER_THRESHOLD = 2
REPEAT_SECONDS = 6 * 3600

SERVICES = (
    "nginx.service",
    "booking-bot.service",
    "booking-web-api.service",
    "servgo-promo-web.service",
    "booking-bot-relay89.service",
    "servgo-mail-worker.service",
    "elitles-tg-proxy.service",
    "postgresql@16-main.service",
    "redis-server.service",
    "dovecot.service",
    "postfix.service",
    "certbot.timer",
    "sto-money-backup.timer",
)
DOCKER_CONTAINERS = (
    "ai-growth-os-api-1",
    "ai-growth-os-worker-1",
    "ai-growth-os-telegram-1",
    "ai-growth-os-postgres-1",
    "sushef-bot-1",
    "sushef-postgres-1",
    "elitlesbot_app",
    "elitlesbot_db",
)
SITES = (
    "promo.servgo.ru",
    "servgo.ru",
    "growth.servgo.ru",
    "mail.servgo.ru",
    "smena.servgo.ru",
    "sto.servgo.ru",
    "tech.servgo.ru",
    "gid.servgo.ru",
)


def command(parts: list[str], *, timeout: int = 7) -> tuple[bool, str]:
    try:
        result = subprocess.run(parts, capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode == 0, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return False, ""


def healthy_http_code(host: str, code: str, transport_ok: bool) -> bool:
    """Authenticated sites may reject anonymous users while still being healthy."""
    if not transport_ok or not code.isdigit():
        return False
    status = int(code)
    return 200 <= status < 400 or (host == "sto.servgo.ru" and status == 401)


def healthy_docker_state(value: str, command_ok: bool) -> bool:
    if not command_ok:
        return False
    running, _, health = value.partition("|")
    return running == "true" and health.strip() not in ("unhealthy", "starting")


def _service_check(name: str) -> tuple[bool, str]:
    ok, value = command(["systemctl", "is-active", name])
    return ok and value == "active", value or "not active"


def _docker_check(name: str) -> tuple[bool, str]:
    ok, value = command([
        "docker", "inspect", "--format",
        "{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}",
        name,
    ])
    return healthy_docker_state(value, ok), value or "container not found"


def _site_check(host: str) -> tuple[bool, str]:
    ok, code = command([
        "curl", "-ksS", "--silent", "--show-error", "-o", "/dev/null",
        "-w", "%{http_code}", "--max-time", "7",
        "--resolve", f"{host}:443:127.0.0.1", f"https://{host}/",
    ], timeout=10)
    return healthy_http_code(host, code, ok), f"HTTP {code or 'unreachable'}"


def _telegram_proxy_check() -> tuple[bool, str]:
    ok, code = command([
        "curl", "-ksS", "-o", "/dev/null", "-w", "%{http_code}",
        "--proxy", "socks5h://127.0.0.1:1089", "--connect-timeout", "4",
        "--max-time", "8", "https://api.telegram.org/",
    ], timeout=11)
    return ok and code.isdigit() and 200 <= int(code) < 400, f"Telegram egress HTTP {code or 'unreachable'}"


def _local_web_check(url: str) -> tuple[bool, str]:
    ok, code = command([
        "curl", "-fsS", "-o", "/dev/null", "-w", "%{http_code}",
        "--max-time", "5", url,
    ], timeout=7)
    return ok and code == "200", f"local HTTP {code or 'unreachable'}"


def _disk_check() -> tuple[bool, str]:
    total, _used, free = shutil.disk_usage("/")
    used_pct = round((total - free) * 100 / total)
    return used_pct < 90, f"disk {used_pct}% used"


def _tls_check(host: str) -> tuple[bool, str]:
    try:
        with socket.create_connection(("127.0.0.1", 443), timeout=4) as sock:
            with ssl.create_default_context().wrap_socket(sock, server_hostname=host) as channel:
                expires = ssl.cert_time_to_seconds(channel.getpeercert()["notAfter"])
        days = int((expires - time.time()) / 86400)
        return days >= 14, f"TLS expires in {days} days"
    except (OSError, ssl.SSLError, KeyError, ValueError):
        return False, "TLS validation failed"


def collect_checks() -> dict[str, tuple[bool, str]]:
    """Check independently failing services in parallel.

    Sequential probes could exceed systemd's 90-second start timeout during
    a widespread outage, precisely when alerts are most important.
    """
    probes: list[tuple[str, Callable[[], tuple[bool, str]]]] = []
    for name in SERVICES:
        probes.append((f"service:{name}", lambda n=name: _service_check(n)))
    for name in DOCKER_CONTAINERS:
        probes.append((f"docker:{name}", lambda n=name: _docker_check(n)))
    for host in SITES:
        probes.append((f"https:{host}", lambda h=host: _site_check(h)))
    probes.extend([
        ("proxy:telegram-egress", _telegram_proxy_check),
        ("promo:standalone", lambda: _local_web_check("http://127.0.0.1:18080/_promo_health")),
        ("webapp:legacy-8080", lambda: _local_web_check("http://127.0.0.1:8080/beauty")),
        ("disk:root", _disk_check),
    ])
    for host in ("promo.servgo.ru", "servgo.ru", "growth.servgo.ru"):
        probes.append((f"tls:{host}", lambda h=host: _tls_check(h)))

    result: dict[str, tuple[bool, str]] = {}
    with ThreadPoolExecutor(max_workers=12, thread_name_prefix="servgo-check") as pool:
        jobs = {pool.submit(probe): key for key, probe in probes}
        for future in as_completed(jobs):
            key = jobs[future]
            try:
                result[key] = future.result()
            except Exception as exc:
                # Never include exception messages: network errors could expose
                # credentials, internal paths or customer data.
                result[key] = False, f"probe failed ({type(exc).__name__})"
    return result


def update_states(
    previous: dict, observations: dict[str, tuple[bool, str]], now: float,
) -> tuple[dict, dict[str, list[tuple[str, str]]]]:
    """Pure transition logic; do not mark notifications delivered here."""
    state = json.loads(json.dumps(previous))
    checks = state.setdefault("checks", {})
    pending: dict[str, list[tuple[str, str]]] = {"down": [], "up": []}
    for key, (healthy, detail) in observations.items():
        item = checks.setdefault(key, {
            "bad": 0, "good": 0, "alarm": False,
            "notified": False, "last_sent": 0, "pending": "",
        })
        item["detail"] = detail[:160]
        if healthy:
            item["good"] = int(item.get("good", 0)) + 1
            item["bad"] = 0
            if item["alarm"] and item["good"] >= RECOVER_THRESHOLD:
                item["alarm"] = False
                item["pending"] = "up" if item.get("notified") else ""
        else:
            item["bad"] = int(item.get("bad", 0)) + 1
            item["good"] = 0
            if item["bad"] >= FAIL_THRESHOLD:
                if not item["alarm"]:
                    item["alarm"] = True
                    item["notified"] = False
                    item["pending"] = "down"
                elif item.get("notified") and now - float(item.get("last_sent", 0)) >= REPEAT_SECONDS:
                    item["pending"] = "down"
        if item.get("pending") == "down" and item["alarm"]:
            pending["down"].append((key, item["detail"]))
        if item.get("pending") == "up" and healthy and not item["alarm"] and item["good"] >= RECOVER_THRESHOLD:
            pending["up"].append((key, item["detail"]))
    return state, pending


def mark_delivered(state: dict, kind: str, keys: list[str], now: float) -> None:
    for key in keys:
        item = state["checks"][key]
        if item.get("pending") != kind:
            continue
        item["pending"] = ""
        if kind == "down":
            item["notified"] = True
            item["last_sent"] = now
        else:
            item["notified"] = False
            item["last_sent"] = now


def save_state(state: dict, path: Path | None = None) -> None:
    # Resolve the state path at call time so test/incident overrides are honored.
    path = path if path is not None else STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def credentials() -> tuple[str, str]:
    token = os.getenv("SERVGO_MONITOR_BOT_TOKEN", "").strip()
    chat = os.getenv("SERVGO_MONITOR_CHAT_ID", "").strip()
    if not token or not chat:
        # Existing Growth bot already has a private owner-notification channel.
        from dotenv import dotenv_values
        env = dotenv_values("/opt/ai_growth_os/.env")
        token = token or str(env.get("TELEGRAM_BOT_TOKEN") or "").strip()
        chat = chat or str(env.get("TELEGRAM_OWNER_CHAT_ID") or "").strip()
    if not token or not chat:
        raise RuntimeError("ServGo monitoring Telegram credentials are not configured")
    return token, chat


async def send_message(message: str) -> bool:
    import aiohttp
    from aiohttp_socks import ProxyConnector

    token, chat = credentials()
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    if len(message) > 3800:
        raise ValueError("Monitoring Telegram message exceeds safe size; use alert_batches")
    payload = {"chat_id": chat, "text": message, "disable_web_page_preview": True}
    timeout = aiohttp.ClientTimeout(total=10)
    for via_proxy in (False, True):
        try:
            connector = ProxyConnector.from_url("socks5://127.0.0.1:1089") if via_proxy else None
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.post(endpoint, json=payload) as response:
                    if response.status == 200:
                        return True
                    # Invalid credentials, blocked chat etc: proxy will not help.
                    if response.status in (400, 401, 403):
                        return False
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            pass
    return False


def message(kind: str, failures: list[tuple[str, str]]) -> str:
    title = "🚨 ServGo: обнаружен сбой" if kind == "down" else "✅ ServGo: восстановлено"
    lines = [title, "", *[f"• {key}: {detail}" for key, detail in failures]]
    if kind == "down":
        lines.extend(("", "Уведомление повторится не чаще одного раза в 6 часов."))
    return "\n".join(lines)


def alert_batches(kind: str, items: list[tuple[str, str]], limit: int = 3500) -> list[tuple[list[tuple[str, str]], str]]:
    """Split incidents without dropping alerts or acknowledging unsent checks."""
    if limit < 350:
        raise ValueError("Telegram batch limit must be at least 350 characters")
    batches: list[tuple[list[tuple[str, str]], str]] = []
    chunk: list[tuple[str, str]] = []
    for item in items:
        if len(message(kind, [item])) > limit:
            raise ValueError("One monitoring incident exceeds Telegram size limit")
        candidate = chunk + [item]
        if chunk and len(message(kind, candidate)) > limit:
            batches.append((chunk, message(kind, chunk)))
            chunk = [item]
        else:
            chunk = candidate
    if chunk:
        batches.append((chunk, message(kind, chunk)))
    return batches


async def run(*, dry_run: bool = False, test_message: bool = False) -> bool:
    if test_message:
        return await send_message("✅ ServGo: тест системы мониторинга. Канал уведомлений работает.")
    observations = collect_checks()
    if dry_run:
        print(json.dumps({k: {"ok": ok, "detail": detail}
                          for k, (ok, detail) in observations.items()},
                         ensure_ascii=False, sort_keys=True))
        return all(ok for ok, _ in observations.values())

    try:
        previous = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        previous = {"checks": {}}

    now = time.time()
    updated, pending = update_states(previous, observations, now)
    save_state(updated)
    all_sent = True
    for kind in ("down", "up"):
        items = pending[kind]
        for batch, text in alert_batches(kind, items):
            try:
                delivered = await send_message(text)
            except Exception as exc:
                print(f"Monitoring notification failed: {type(exc).__name__}")
                delivered = False
            if delivered:
                mark_delivered(updated, kind, [key for key, _ in batch], now)
                save_state(updated)
            else:
                all_sent = False
    summary = {
        "healthy": sum(1 for ok, _ in observations.values() if ok),
        "checks": len(observations),
        "open_incidents": sum(1 for item in updated["checks"].values() if item["alarm"]),
        "delivery_ok": all_sent,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return all_sent


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="No alerts and no state changes")
    parser.add_argument("--test-message", action="store_true", help="Send a single explicit test")
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(run(dry_run=args.check, test_message=args.test_message)) else 1)
