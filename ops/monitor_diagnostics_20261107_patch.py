#!/usr/bin/env python3
"""Targeted, guarded upgrade of ServGo monitor on the existing server.

No credentials are read by this patcher. It writes a candidate to an explicitly
chosen path, never touches the running monitor or its state directly.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

SIGNATURE = "# ServGo monitor diagnostics v1 (2026-11-07)"

EXTRAS = r'''
def _safe_monitor_error(stderr: str) -> str:
    """Preserve curl's error code and reason, never credentials or URLs."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    reason = lines[-1] if lines else "stderr пуст"
    reason = re.sub(r"https?://[^\s\"']+", "[URL]", reason, flags=re.I)
    reason = re.sub(r"\b\d{7,12}:[A-Za-z0-9_-]{20,}\b", "[TOKEN]", reason)
    reason = re.sub(r"\b(?:token|secret|password|authorization|api[_-]?key)=[^\s;]+",
                    "[REDACTED]", reason, flags=re.I)
    reason = re.sub(r"[A-Za-z0-9_./+=-]{65,}", "[REDACTED]", reason)
    reason = re.sub(r"[\x00-\x1f\x7f]", " ", reason)
    return reason[:180]


def command_diagnostic(parts: list[str], *, timeout: int = 7) -> tuple[bool, str, str]:
    """Return status, stdout HTTP code, safe subprocess error message."""
    try:
        proc = subprocess.run(parts, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return False, "", f"локальный запуск проверки превысил {timeout} с"
    except OSError as exc:
        return False, "", f"не удалось запустить проверку: {type(exc).__name__}"
    stdout = proc.stdout.strip()
    if proc.returncode:
        return False, stdout, (
            f"curl exit {proc.returncode}: {_safe_monitor_error(proc.stderr or '')}")
    return True, stdout, ""


def _incident_clock(ts: float) -> str:
    if not ts:
        return "время начала не установлено"
    return datetime.fromtimestamp(float(ts), timezone.utc).astimezone().strftime(
        "%d.%m.%Y %H:%M:%S %Z")


def _incident_duration(seconds: float) -> str:
    elapsed = max(0, int(round(seconds)))
    hours, remainder = divmod(elapsed, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} ч {minutes} мин {secs} с"
    if minutes:
        return f"{minutes} мин {secs} с"
    return f"{secs} с"


'''


TRANSITIONS = r'''def update_states(
    previous: dict, observations: dict[str, tuple[bool, str]], now: float,
) -> tuple[dict, dict[str, list[tuple[str, str]]]]:
    """Durable incident chronology based on sampled observations.

    The first failed sample opens the estimated outage interval; two failures
    confirm DOWN. First healthy sample closes it only after two successful
    samples confirm UP. The end-to-end exact start/end time between probes is
    not observable, so duration is marked approximate in notifications.
    """
    state = json.loads(json.dumps(previous))
    checks = state.setdefault("checks", {})
    pending: dict[str, list[tuple[str, str]]] = {"down": [], "up": []}

    for key, (healthy, detail) in observations.items():
        item = checks.setdefault(key, {
            "bad": 0, "good": 0, "alarm": False,
            "notified": False, "last_sent": 0, "pending": "",
        })
        item["detail"] = detail[:300]
        if healthy:
            item["good"] = int(item.get("good", 0)) + 1
            item["bad"] = 0
            if item.get("alarm"):
                if not item.get("first_good_at"):
                    item["first_good_at"] = now
                if item["good"] >= RECOVER_THRESHOLD:
                    item["alarm"] = False
                    item["pending"] = "up" if item.get("notified") else ""
                    end = float(item.get("first_good_at") or now)
                    item["recovered_at"] = end
                    start = float(item.get("down_since") or 0)
                    item["outage_seconds"] = max(0, end - start) if start else None
            elif item.get("pending") != "up":
                # An isolated failed probe did not become a confirmed incident.
                item["down_since"] = 0
                item["first_good_at"] = 0
                item["start_late"] = False
        else:
            old_bad = int(item.get("bad", 0))
            if not item.get("down_since"):
                item["down_since"] = now
                # Older active incident records have no timestamp to migrate.
                item["start_late"] = bool(item.get("alarm"))
            item["last_error"] = detail[:300]
            item["first_good_at"] = 0
            item["bad"] = old_bad + 1
            item["good"] = 0
            if item["bad"] >= FAIL_THRESHOLD:
                if not item.get("alarm"):
                    item["alarm"] = True
                    item["notified"] = False
                    item["pending"] = "down"
                elif item.get("notified") and now - float(item.get("last_sent", 0)) >= REPEAT_SECONDS:
                    item["pending"] = "down"

        if item.get("pending") == "down" and item.get("alarm"):
            start = float(item.get("down_since") or 0)
            elapsed = _incident_duration(now - start) if start else "неизвестно"
            caution = " (с момента обновления мониторинга)" if item.get("start_late") else ""
            info = (f"Ошибка: {item.get('last_error', item['detail'])}; "
                    f"первый сбой: {_incident_clock(start)}{caution}; "
                    f"длится по замерам: ~{elapsed}")
            pending["down"].append((key, info))

        if item.get("pending") == "up" and not item.get("alarm"):
            start = float(item.get("down_since") or 0)
            end = float(item.get("recovered_at") or now)
            seconds = item.get("outage_seconds")
            elapsed = ("~" + _incident_duration(float(seconds))
                       if seconds is not None else "неизвестна")
            legacy = " (отсчёт не раньше обновления)" if item.get("start_late") else ""
            info = (f"Восстановлено: {item['detail']}; "
                    f"последняя ошибка: {item.get('last_error', 'не сохранена')}; "
                    f"длительность по замерам: {elapsed}{legacy}; "
                    f"с {_incident_clock(start)} до {_incident_clock(end)}")
            pending["up"].append((key, info))
    return state, pending


'''


def change_once(code: str, before: str, after: str) -> str:
    count = code.count(before)
    if count != 1:
        raise RuntimeError(f"Expected one patch anchor, found {count}: {before[:70]!r}")
    return code.replace(before, after, 1)


def patch(source: str) -> str:
    if SIGNATURE in source:
        raise RuntimeError("Monitor diagnostics already installed; no double patch")
    source = change_once(source, "import shutil\n", "import re\nimport shutil\n")
    source = change_once(source,
                         "\n\ndef healthy_http_code(",
                         "\n\n" + SIGNATURE + "\n" + EXTRAS + "def healthy_http_code(")

    # Change the site HTTP check and keep its original URL, timeout, flags.
    region_start = source.index("    for host in SITES:")
    site_result = source.index('        result[f"https:{host}"]', region_start)
    begin = source.rfind("        ok, code = command([", region_start, site_result)
    if begin == -1:
        raise RuntimeError("Site HTTP check invocation changed")
    source = source[:begin] + source[begin:].replace(
        "        ok, code = command([", "        ok, code, error = command_diagnostic([", 1)
    source = change_once(
        source,
        '        result[f"https:{host}"] = (healthy_http_code(host, code, ok), f"HTTP {code or \'unreachable\'}")',
        '        site_ok = healthy_http_code(host, code, ok)\n'
        '        result[f"https:{host}"] = (site_ok, f"HTTP {code or \'unreachable\'}" +\n'
        '                                    (f"; {error}" if error and not site_ok else ""))'
    )

    # Keep preconfigured Telegram URL and SOCKS5 proxy unchanged.
    target = source.index('    result["proxy:telegram-egress"]')
    begin = source.rfind("    ok, code = command([", site_result, target)
    if begin == -1:
        raise RuntimeError("Telegram proxy invocation changed")
    source = source[:begin] + source[begin:].replace(
        "    ok, code = command([", "    ok, code, error = command_diagnostic([", 1)
    source = change_once(
        source,
        '    result["proxy:telegram-egress"] = (ok and code.isdigit() and 200 <= int(code) < 400,\n'
        '                                       f"Telegram egress HTTP {code or \'unreachable\'}")',
        '    proxy_ok = ok and code.isdigit() and 200 <= int(code) < 400\n'
        '    proxy_detail = f"Telegram через SOCKS5 HTTP {code or \'нет ответа\'}"\n'
        '    if not proxy_ok:\n'
        '        proxy_detail += f"; {error or \'HTTP ответ вне диапазона 200-399\'}"\n'
        '    result["proxy:telegram-egress"] = (proxy_ok, proxy_detail)'
    )

    # The remaining two HTTP endpoint probes also get safe details.
    for key in ('promo:standalone', 'webapp:legacy-8080'):
        result_at = source.index(f'    result["{key}"]')
        begin = source.rfind("    ok, code = command([", 0, result_at)
        if begin == -1:
            raise RuntimeError(f"Check invocation changed for {key}")
        source = source[:begin] + source[begin:].replace(
            "    ok, code = command([", "    ok, code, error = command_diagnostic([", 1)

    source = change_once(
        source,
        '    result["promo:standalone"] = (ok and code == "200", f"local HTTP {code or \'unreachable\'}")',
        '    promo_ok = ok and code == "200"\n'
        '    result["promo:standalone"] = (promo_ok, f"local HTTP {code or \'unreachable\'}" +\n'
        '                                  (f"; {error}" if error and not promo_ok else ""))'
    )
    source = change_once(
        source,
        '    result["webapp:legacy-8080"] = (ok and code == "200",\n'
        '                                     f"legacy HTTP {code or \'unreachable\'}")',
        '    legacy_ok = ok and code == "200"\n'
        '    result["webapp:legacy-8080"] = (legacy_ok, f"legacy HTTP {code or \'unreachable\'}" +\n'
        '                                     (f"; {error}" if error and not legacy_ok else ""))'
    )

    old_begin = source.index("def update_states(")
    old_end = source.index("def mark_delivered(", old_begin)
    if source[old_begin:old_end].count("def update_states(") != 1:
        raise RuntimeError("Unexpected transition block")
    source = source[:old_begin] + TRANSITIONS + source[old_end:]
    compile(source, "<monitor-candidate>", "exec")
    return source


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("source")
    args.add_argument("candidate")
    ns = args.parse_args()
    source = Path(ns.source).read_text(encoding="utf8")
    candidate = patch(source)
    Path(ns.candidate).write_text(candidate, encoding="utf8")
    print("Monitor patch prepared; candidate source syntax is valid.")


if __name__ == "__main__":
    main()
