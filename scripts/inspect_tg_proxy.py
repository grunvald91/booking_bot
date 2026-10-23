"""Read-only look at the tg.servgo.ru web proxy on relay 89. Prints config of the tg.servgo.ru site, statuses and
reachability only; every secret-looking value is masked, nothing is written on the relay."""
import base64
import hashlib
import logging
import os
import re

import paramiko

RELAY = "89.125.90.101"
RELAY_FP = "+SqoDNS4YTI9OKHifsEpbLwWof6oXONbdFX+GLSTlC0"
logging.getLogger("paramiko").setLevel(logging.CRITICAL)


class Pinned(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        fp = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        if key.get_name() != "ssh-ed25519" or fp != RELAY_FP:
            raise paramiko.SSHException("Pinned SSH host key mismatch")
        client.get_host_keys().add(hostname, key.get_name(), key)


def mask(text):
    text = re.sub(r"\b[0-9a-fA-F]{24,}\b", "<hex-masked>", text)
    text = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "<ip>", text)
    text = re.sub(r"(?i)((?:secret|password|token|key)\s*[=: ]+)\S+", r"\1<masked>", text)
    return text


def run(client, command, timeout=40):
    _, out, _ = client.exec_command(command, timeout=timeout)
    return out.read().decode("utf-8", "replace").strip()


def section(title, body):
    print("\n=== " + title)
    print(mask(body) if body else "(empty)")


def main():
    password = os.environ.get("RELAY_PASSWORD")
    if not password:
        raise RuntimeError("RELAY89_SSH_PASSWORD is missing")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(Pinned())
    client.connect(RELAY, port=22, username="root", password=password, look_for_keys=False, allow_agent=False,
                   timeout=12, banner_timeout=25, auth_timeout=15)
    try:
        section("nginx", run(client, "nginx -v 2>&1; systemctl is-active nginx; ls /etc/nginx/sites-enabled /etc/nginx/conf.d 2>&1"))
        full = run(client, "nginx -T 2>/dev/null", timeout=60)
        files = re.split(r"(?m)^# configuration file ", full)
        shown = 0
        for chunk in files:
            if "tg.servgo.ru" in chunk or "oauth.telegram.org" in chunk or "telegram.org" in chunk:
                name, _, body = chunk.partition("\n")
                section("config file mentioning tg.servgo.ru/telegram.org: " + name.strip(), body)
                shown += 1
        print("\nfiles shown:", shown)
        section("certificates", run(client, "ls /etc/letsencrypt/live 2>&1; for d in /etc/letsencrypt/live/tg*; do "
                                    "[ -d \"$d\" ] && openssl x509 -enddate -subject -noout -in $d/fullchain.pem; done 2>&1"))
        probes = [
            "/js/telegram-web-app.js",
            "/js/telegram-widget.js?22",
            "/embed/Sochiservice_bot?origin=https%3A%2F%2Fservgo.ru&return_to=https%3A%2F%2Fservgo.ru%2Flogin",
            "/auth?bot_id=1&origin=https%3A%2F%2Fservgo.ru",
            "/css/widget-frame.css?75",
            "/js/widget-frame.js?68",
        ]
        lines = []
        for path in probes:
            lines.append(path.split("?")[0] + " -> " + run(
                client, "curl -sS -m 15 -o /dev/null -w '%{http_code} %{content_type} %{size_download}B' "
                        "--resolve tg.servgo.ru:443:127.0.0.1 'https://tg.servgo.ru" + path + "' 2>&1 | tail -1"))
        section("local probes of the proxy itself (status, type, size)", "\n".join(lines))
        lines = []
        for url in ("https://telegram.org/js/telegram-widget.js?22",
                    "https://oauth.telegram.org/embed/Sochiservice_bot?origin=https%3A%2F%2Fservgo.ru",
                    "https://oauth.telegram.org/auth?bot_id=1&origin=https%3A%2F%2Fservgo.ru"):
            lines.append(url.split("?")[0] + " -> " + run(
                client, "curl -sS -m 15 -o /dev/null -w '%{http_code} %{content_type}' '" + url + "' 2>&1 | tail -1"))
        section("relay's own access to Telegram", "\n".join(lines))
        section("what the proxy changes in the page (first scripts of the Telegram embed, links only)",
                run(client, "curl -sS -m 15 --resolve tg.servgo.ru:443:127.0.0.1 "
                            "'https://tg.servgo.ru/embed/Sochiservice_bot?origin=https%3A%2F%2Fservgo.ru' 2>&1 | "
                            "grep -o -E '(src|href)=\"[^\"]+\"' | head -12"))
        section("listeners and process names", run(client, "ss -ltnH 2>/dev/null | awk '{print $4}' | sort -u | head -20; "
                                                           "ps -eo comm | sort | uniq -c | sort -rn | head -12"))
        section("nginx error log tail", run(client, "tail -n 12 /var/log/nginx/error.log 2>&1"))
        section("disk and memory", run(client, "df -h / | tail -1; free -m | sed -n 2p"))
    finally:
        client.close()


if __name__ == "__main__":
    main()
