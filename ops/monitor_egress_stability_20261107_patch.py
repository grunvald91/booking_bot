#!/usr/bin/env python3
"""Safe, idempotency-guarded patch for ServGo's already-installed monitor v1.

Run on a *copy* of production script; syntax/test it before replacing live file.
"""
from __future__ import annotations
import argparse
from pathlib import Path

MARKER = "# ServGo monitor stable Telegram egress v2 (2026-11-07)"
V1 = "# ServGo monitor diagnostics v1 (2026-11-07)"


def once(source: str, old: str, new: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"Unexpected source shape: expected one anchor; found {count}: {old[:60]!r}")
    return source.replace(old, new, 1)


def patch(source: str) -> str:
    if MARKER in source:
        raise ValueError("Stable egress monitor already installed; refusing double-patch")
    if V1 not in source:
        raise ValueError("Expected v1 monitor not found; refusing unsafe patch")

    source = once(source, "RECOVER_THRESHOLD = 2\n",
                  "RECOVER_THRESHOLD = 2\nRECOVERY_STABLE_SECONDS = 15 * 60\n" + MARKER + "\n")

    # The existing four-second SOCKS5 connection limit is below observed valid
    # HTTPS handshake latency (up to 7.6 seconds in live 2026-11-07 probes).
    end = source.index('    proxy_ok = ')
    begin = source.rfind('    ok, code, error = command_diagnostic([', 0, end)
    if begin < 0:
        raise ValueError("Could not locate existing Telegram curl call")
    old_block = source[begin:end]
    if old_block.count('socks5h://127.0.0.1:1089') != 1:
        raise ValueError("SOCKS5 target changed; stop and inspect")
    new_block = once(old_block,
                     '    ok, code, error = command_diagnostic([',
                     '    proxy_command = [')
    new_block = once(new_block, '"--connect-timeout", "4"',
                     '"--connect-timeout", "10"')
    new_block = once(new_block, '"--max-time", "8"',
                     '"--max-time", "18"')
    new_block = once(new_block, '    ], timeout=11)\n',
                     '''    ]
    ok, code, error = command_diagnostic(proxy_command, timeout=21)
    proxy_retried = False
    if not (ok and code.isdigit() and 200 <= int(code) < 400):
        first_error = error
        proxy_retried = True
        time.sleep(1)
        ok, code, error = command_diagnostic(proxy_command, timeout=21)
        if not (ok and code.isdigit() and 200 <= int(code) < 400):
            error = f"две попытки: {first_error}; {error}"[:300]
''')
    source = source[:begin] + new_block + source[end:]

    source = once(source,
                  '    proxy_detail = f"Telegram через SOCKS5 HTTP {code or \'нет ответа\'}"\n',
                  '    proxy_detail = f"Telegram через SOCKS5 HTTP {code or \'нет ответа\'}"\n'
                  '    if proxy_ok and proxy_retried:\n'
                  '        proxy_detail += "; успешно со второй попытки"\n')

    # Do not resolve a real alarm after only two good samples: short good
    # interludes on unstable tunnels were generating UP/DOWN messages every
    # few minutes despite a six-hour repeat limit for *continuing* incidents.
    source = once(source,
                  '                if item["good"] >= RECOVER_THRESHOLD:\n',
                  '                if (item["good"] >= RECOVER_THRESHOLD and\n'
                  '                        now - float(item.get("first_good_at") or now) >= RECOVERY_STABLE_SECONDS):\n')
    source = once(source,
                  '            info = (f"Восстановлено: {item[\'detail\']}; "\n',
                  '            info = (f"Восстановлено (15 минут устойчивой доступности): {item[\'detail\']}; "\n')
    compile(source, "<servgo-monitor-egress-v2>", "exec")
    return source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("production_copy")
    parser.add_argument("candidate")
    args = parser.parse_args()
    original = Path(args.production_copy).read_text(encoding="utf-8")
    Path(args.candidate).write_text(patch(original), encoding="utf-8")
    print("candidate_built=yes, live_monitor_untouched=yes")


if __name__ == "__main__":
    main()
