"""Read-only diagnosis: why the public list of places may not load. Changes nothing on the server."""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.deploy_business_creation_and_reminders import ROOT, WEB_SERVICE, BOT_SERVICE, connect, run  # noqa: E402


def safe(text: str) -> str:
    text = re.sub(r'bot[0-9]{6,}:[A-Za-z0-9_-]{25,}', 'bot[REDACTED]', text)
    text = re.sub(r'(?i)(token|password|api_key|secret|cookie|authorization)\s*[=:]\s*[^\s,;]+', r'\1=[REDACTED]', text)
    text = re.sub(r'\+?\d[\d\s()-]{9,}\d', '[PHONE]', text)
    text = re.sub(r'[\w.+-]+@[\w-]+\.[\w.-]+', '[EMAIL]', text)
    return text[:240]


def show(client, title, command, timeout=40, limit=60):
    try:
        out = run(client, command, timeout)
    except Exception as exc:  # keep going: each probe is independent
        out = "probe_failed: " + type(exc).__name__
    lines = out.splitlines()
    print("== " + title)
    for line in lines[-limit:]:
        print("  " + safe(line))


def main():
    password = os.environ["SERVGO_PASSWORD"]
    client = connect(password)
    try:
        show(client, "services", "systemctl is-active %s %s nginx postgresql 2>&1; systemctl show %s -p NRestarts -p ActiveEnterTimestamp" % (WEB_SERVICE, BOT_SERVICE, WEB_SERVICE))
        show(client, "load/memory/disk", "uptime; free -m | head -3; df -h / /opt 2>/dev/null | head -4")
        show(client, "local api timings", "for p in /businesses /businesses/16 /businesses/6; do curl -s -o /dev/null --max-time 15 -w \"$p http=%{http_code} time=%{time_total}s size=%{size_download}\\n\" http://127.0.0.1:8000$p; done")
        show(client, "db connections", "sudo -u postgres psql -Atc \"select state,count(*) from pg_stat_activity group by 1\" 2>&1 | head -10")
        show(client, "web api errors (3h)", "journalctl -u %s --since=-3h --no-pager -o short-iso | grep -iE 'error|exception|traceback|timeout|timed out|pool|too many|refused|killed' | tail -40" % WEB_SERVICE)
        show(client, "web api status codes (1h)", "journalctl -u %s --since=-1h --no-pager 2>/dev/null | grep -oE '\" [0-9]{3} ' | sort | uniq -c | sort -rn | head" % WEB_SERVICE)
        show(client, "nginx errors", "tail -n 400 /var/log/nginx/error.log 2>/dev/null | grep -vE 'favicon' | tail -25")
        show(client, "nginx 5xx/slow (access, last 2000)", "tail -n 2000 /var/log/nginx/access.log 2>/dev/null | awk '$9>=500{c[$9\" \"$7]++} END{for(k in c) print c[k], k}' | sort -rn | head -15")
        show(client, "oom/kills", "dmesg -T 2>/dev/null | grep -iE 'out of memory|killed process' | tail -5; journalctl -k --since=-24h --no-pager 2>/dev/null | grep -iE 'out of memory|killed process' | tail -5")
    finally:
        client.close()


if __name__ == "__main__":
    main()
