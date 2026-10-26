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
        show(client, "nginx tls lines", "grep -rhE 'server_name|ssl_certificate |ssl_protocols|ssl_ciphers|listen |http2|add_header Strict' /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | sed 's/^ *//' | sort | uniq -c | sort -rn | head -40")
        show(client, "certificates on disk", "for f in $(grep -rhoE 'ssl_certificate +[^;]+' /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | awk '{print $2}' | sort -u); do echo \"-- $f\"; openssl x509 -in $f -noout -subject -issuer -dates -ext subjectAltName 2>&1 | head -6; echo chain_certs=$(grep -c 'BEGIN CERT' $f); done")
        show(client, "served chain (from the server itself)", "echo | openssl s_client -connect 127.0.0.1:443 -servername servgo.ru -showcerts 2>/dev/null | grep -E '^ *[0-9] s:|^   i:|Verify return|Protocol|Cipher is' | head -12")
        show(client, "renewal", "systemctl list-timers --no-pager 2>/dev/null | grep -iE 'certbot|acme' ; ls /etc/letsencrypt/live 2>/dev/null; certbot certificates 2>/dev/null | grep -E 'Certificate Name|Domains|Expiry' | head -20")
        show(client, "dns records as seen by the server", "for d in servgo.ru www.servgo.ru tg.servgo.ru; do echo $d A=$(dig +short A $d | tr '\\n' ' ') AAAA=$(dig +short AAAA $d | tr '\\n' ' '); done")
        show(client, "response headers", "curl -sSI --max-time 10 https://servgo.ru/ | head -15")
        show(client, "index timing from the server", "curl -s -o /dev/null --max-time 20 -w 'index total=%{time_total}s tls=%{time_appconnect}s size=%{size_download}\\n' https://servgo.ru/")
    finally:
        client.close()


if __name__ == "__main__":
    main()
