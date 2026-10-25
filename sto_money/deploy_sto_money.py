"""Выкладка учёта выручки по бокам СТО на сервер ServGo (sto.servgo.ru) и приём зашифрованных записей.

Режимы:
  python sto_money/deploy_sto_money.py              APPLY=false — только проверка сервера, ничего не меняется;
                                                    APPLY=true  — установка/обновление сервиса и nginx.
  python sto_money/deploy_sto_money.py --inbox DIR  загрузить новые файлы *.cms из DIR на сервер и применить их.

Что ставится (основной бот, booking-bot и существующие сайты не затрагиваются и не перезапускаются):
  /opt/sto_money                          код, страница, база, резервные копии, ключ приёма записей;
  sto-money.service                       сервис на 127.0.0.1:8095 от отдельного пользователя stomoney;
  sto-money-backup.timer                  ежедневная копия базы;
  новый файл конфигурации nginx           sto.servgo.ru: вход по логину и паролю, проксирование на сервис;
  /etc/nginx/sto_money/htpasswd           логины (создаются из зашифрованной записи set_users).
При любой ошибке после первого изменения всё добавленное в nginx и systemd убирается, данные остаются.

Секреты (пароль сервера, закрытый ключ) нигде не печатаются. В вывод попадают только факты о сервере
и короткие коды: вывод виден в публичном логе Actions.
"""
import argparse
import base64
import hashlib
import logging
import os
import re
import shlex
import sys
import time
from pathlib import Path

HOST = "155.212.162.47"
FP = "uQJp3lT4golKb3lsDTCFozGWR1ihlu1w/Oa4cSzCdpU"
DOMAIN = "sto.servgo.ru"
PORT = 8095
ROOT = "/opt/sto_money"
APP_USER = "stomoney"
SERVICE = "sto-money.service"
BACKUP_SERVICE = "sto-money-backup.service"
BACKUP_TIMER = "sto-money-backup.timer"
HTPASSWD_DIR = "/etc/nginx/sto_money"
HTPASSWD = HTPASSWD_DIR + "/htpasswd"
KEY_PATH = ROOT + "/keys/inbox_key.pem"
CERT_PATH = ROOT + "/keys/entry_cert.pem"
LOCAL = Path(__file__).resolve().parent
CODE_FILES = {
    "server/app.py": ROOT + "/server/app.py",
    "server/store.py": ROOT + "/server/store.py",
    "server/inbox.py": ROOT + "/server/inbox.py",
    "web/index.html": ROOT + "/web/index.html",
}
logging.getLogger("paramiko").setLevel(logging.CRITICAL)
report = []


class DeployError(RuntimeError):
    pass


def note(text):
    print(text)
    report.append(text)


# ---------------------------------------------------------------- чистые функции (покрыты тестами)

def normalize_key(text):
    """Закрытый ключ из секрета GitHub: приводит переводы строк, проверяет рамку PEM. Содержимое не печатает."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 3 or lines[0] != "-----BEGIN EC PRIVATE KEY-----" or lines[-1] != "-----END EC PRIVATE KEY-----":
        raise DeployError("STO_PRIVATE_KEY is not a PEM EC private key")
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", "".join(lines[1:-1])):
        raise DeployError("STO_PRIVATE_KEY body is not valid base64")
    return "\n".join(lines) + "\n"


def service_unit(python):
    return (
        "[Unit]\nDescription=STO money tracker (%s)\nAfter=network.target\n\n"
        "[Service]\nType=simple\nUser=%s\nGroup=%s\nWorkingDirectory=%s\n"
        "Environment=STO_DB=%s/data/sto.db STO_WEB=%s/web STO_PORT=%d PYTHONDONTWRITEBYTECODE=1\n"
        "ExecStart=%s %s/server/app.py\nRestart=always\nRestartSec=5\n"
        "NoNewPrivileges=true\nProtectSystem=strict\nProtectHome=true\nPrivateTmp=true\nReadWritePaths=%s/data\n\n"
        "[Install]\nWantedBy=multi-user.target\n"
    ) % (DOMAIN, APP_USER, APP_USER, ROOT, ROOT, ROOT, PORT, python, ROOT, ROOT)


def backup_units(python):
    service = (
        "[Unit]\nDescription=STO money tracker: daily database copy\n\n"
        "[Service]\nType=oneshot\nUser=%s\nGroup=%s\n"
        "ExecStart=%s %s/server/inbox.py --db %s/data/sto.db --backup-dir %s/backups --backup-only\n"
    ) % (APP_USER, APP_USER, python, ROOT, ROOT, ROOT)
    timer = ("[Unit]\nDescription=STO money tracker: daily database copy\n\n"
             "[Timer]\nOnCalendar=daily\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n")
    return service, timer


def nginx_conf(cert_dir):
    """Файл конфигурации nginx. cert_dir — каталог в /etc/letsencrypt/live, подходящий для домена, либо None.

    Имя вошедшего пользователя nginx кладёт в X-Auth-User и затирает любое значение от клиента.
    """
    proxy = (
        "    auth_basic \"STO\";\n    auth_basic_user_file %s;\n    client_max_body_size 128k;\n"
        "    location ^~ /.well-known/acme-challenge/ {\n        auth_basic off;\n        root /var/www/html;\n    }\n"
        "    location / {\n        proxy_pass http://127.0.0.1:%d;\n        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "        proxy_set_header X-Auth-User $remote_user;\n        proxy_read_timeout 30s;\n    }\n"
    ) % (HTPASSWD, PORT)
    if cert_dir:
        live = "/etc/letsencrypt/live/" + cert_dir
        return (
            "server {\n    listen 80;\n    server_name %s;\n"
            "    location ^~ /.well-known/acme-challenge/ {\n        root /var/www/html;\n    }\n"
            "    location / {\n        return 301 https://$host$request_uri;\n    }\n}\n\n"
            "server {\n    listen 443 ssl;\n    server_name %s;\n"
            "    ssl_certificate %s/fullchain.pem;\n    ssl_certificate_key %s/privkey.pem;\n%s}\n"
        ) % (DOMAIN, DOMAIN, live, live, proxy)
    return "server {\n    listen 80;\n    server_name %s;\n%s}\n" % (DOMAIN, proxy)


# ---------------------------------------------------------------- связь с сервером

def connect():
    import paramiko

    class PinnedKey(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            fingerprint = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
            if fingerprint != FP:
                raise paramiko.SSHException("ServGo SSH host key mismatch")
            client.get_host_keys().add(hostname, key.get_name(), key)

    password = os.environ.get("SERVGO_PASSWORD")
    if not password:
        raise DeployError("Missing GitHub SSH secret")
    for attempt in range(3):
        candidate = paramiko.SSHClient()
        candidate.set_missing_host_key_policy(PinnedKey())
        try:
            candidate.connect(HOST, port=22, username="root", password=password, allow_agent=False, look_for_keys=False,
                              timeout=12, banner_timeout=25, auth_timeout=15)
            return candidate
        except Exception:
            candidate.close()
            if attempt == 2:
                raise DeployError("ServGo SSH unavailable") from None
            time.sleep(3)


def run(client, command, what, timeout=90, ok=(0,)):
    """Выполняет команду, возвращает stdout. Текст ошибок команды не печатается (в нём могут быть данные)."""
    _, stdout, _ = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace").strip()
    code = stdout.channel.recv_exit_status()
    if code not in ok:
        raise DeployError("remote step failed: %s (exit %s)" % (what, code))
    return out


def put(sftp, path, data, mode=0o644):
    temp = path + ".sto.tmp"
    try:
        sftp.remove(temp)
    except IOError:
        pass
    with sftp.open(temp, "wx") as out:
        out.write(data)
    sftp.chmod(temp, mode)
    sftp.posix_rename(temp, path)


def exists(client, path):
    return run(client, "test -e %s && echo yes || echo no" % shlex.quote(path), "exists") == "yes"


# ---------------------------------------------------------------- проверка сервера (только чтение)

def gather_facts(client):
    q = shlex.quote
    f = {}
    f["python"] = run(client, "command -v python3 || true", "python path")
    f["python_ok"] = bool(f["python"]) and run(
        client, "python3 -c 'import sqlite3,sys; print(sys.version_info>=(3,8) and sqlite3.sqlite_version_info>=(3,24))'",
        "python version") == "True"
    f["openssl_cms"] = run(client, "openssl cms -help >/dev/null 2>&1 && echo yes || echo no", "openssl cms") == "yes"
    f["nginx"] = run(client, "command -v nginx || true", "nginx path") != ""
    f["nginx_ok"] = f["nginx"] and run(client, "nginx -t >/dev/null 2>&1 && echo yes || echo no", "nginx -t") == "yes"
    includes = run(client, "nginx -T 2>/dev/null | grep -E '^[[:space:]]*include[[:space:]]+/etc/nginx/(conf\\.d|sites-enabled)/' | head -5 || true",
                   "nginx includes")
    f["conf_d"] = "/etc/nginx/conf.d/" in includes
    f["sites_enabled"] = "/etc/nginx/sites-enabled/" in includes
    f["nginx_user"] = run(client, "nginx -T 2>/dev/null | awk '/^user /{gsub(\";\",\"\",$2); print $2; exit}' || true", "nginx user") or "www-data"
    f["own_conf"] = exists(client, "/etc/nginx/conf.d/sto-money.conf") or exists(client, "/etc/nginx/sites-available/sto-money")
    # имя уже занято чужим server-блоком? (собственный файл при повторной выкладке не считается)
    f["name_taken"] = (not f["own_conf"]) and run(
        client, "nginx -T 2>/dev/null | grep -E 'server_name[[:space:]].*\\b%s\\b' | wc -l" % DOMAIN.replace(".", "\\."),
        "name taken") not in ("", "0")
    f["cert_dir"] = run(
        client,
        "for d in /etc/letsencrypt/live/*/; do n=$(basename \"$d\"); [ -f \"$d/fullchain.pem\" ] || continue; "
        "openssl x509 -in \"$d/fullchain.pem\" -noout -checkend 864000 >/dev/null 2>&1 || continue; "
        "openssl x509 -in \"$d/fullchain.pem\" -noout -ext subjectAltName 2>/dev/null | tr ',' '\\n' | "
        "grep -Eq 'DNS:(%s|\\*\\.servgo\\.ru)[[:space:]]*$' && { echo \"$n\"; break; }; done; true" % DOMAIN.replace(".", "\\."),
        "certificate lookup")
    f["certbot"] = run(client, "command -v certbot || true", "certbot path") != ""
    f["certbot_nginx"] = f["certbot"] and run(client, "certbot plugins 2>/dev/null | grep -c nginx || true", "certbot plugins") not in ("", "0")
    f["service_active"] = run(client, "systemctl is-active %s || true" % SERVICE, "service state") == "active"
    f["port_busy"] = run(client, "ss -ltn 2>/dev/null | awk '{print $4}' | grep -c ':%d$' || true" % PORT, "port check") not in ("", "0")
    f["user_exists"] = run(client, "id %s >/dev/null 2>&1 && echo yes || echo no" % APP_USER, "user check") == "yes"
    f["runuser"] = run(client, "command -v runuser || true", "runuser path") != ""
    f["installed"] = exists(client, ROOT + "/server/app.py")
    f["key_present"] = exists(client, KEY_PATH)
    f["htpasswd_present"] = exists(client, HTPASSWD)
    f["disk_free_mb"] = run(client, "df -Pm /opt | awk 'NR==2{print $4}'", "disk")
    return f


def blockers(f):
    problems = []
    if not f["python_ok"]:
        problems.append("python3 >= 3.8 with sqlite >= 3.24 is required")
    if not f["openssl_cms"]:
        problems.append("openssl cms is not available")
    if not f["nginx"] or not f["nginx_ok"]:
        problems.append("nginx is missing or its current configuration does not pass nginx -t")
    if not (f["conf_d"] or f["sites_enabled"]):
        problems.append("nginx does not include conf.d or sites-enabled")
    if f["name_taken"]:
        problems.append("%s is already defined in nginx outside this service" % DOMAIN)
    if f["port_busy"] and not f["service_active"]:
        problems.append("port %d is already in use by another program" % PORT)
    if not f["cert_dir"] and not (f["certbot"] and f["certbot_nginx"]):
        problems.append("no valid certificate covers %s and certbot with the nginx plugin is unavailable" % DOMAIN)
    if not f["runuser"]:
        problems.append("runuser is not available")
    return problems


def describe(f, problems):
    note("python3=%s nginx=%s nginx_test=%s conf.d=%s sites-enabled=%s nginx_user=%s" % (
        "ok" if f["python_ok"] else "no", "yes" if f["nginx"] else "no", "ok" if f["nginx_ok"] else "fail",
        f["conf_d"], f["sites_enabled"], f["nginx_user"]))
    note("certificate=%s certbot=%s certbot_nginx=%s port_%d_busy=%s name_taken=%s" % (
        f["cert_dir"] or "none", f["certbot"], f["certbot_nginx"], PORT, f["port_busy"], f["name_taken"]))
    note("installed=%s service_active=%s key_present=%s htpasswd_present=%s user_exists=%s disk_free_mb=%s" % (
        f["installed"], f["service_active"], f["key_present"], f["htpasswd_present"], f["user_exists"], f["disk_free_mb"]))
    note("blockers: " + ("; ".join(problems) if problems else "none"))


# ---------------------------------------------------------------- установка

def selftest_key(client):
    q = shlex.quote
    cmd = ("echo ok | openssl cms -encrypt -aes-256-cbc -outform PEM -recip %s | "
           "runuser -u %s -- openssl cms -decrypt -inform PEM -inkey %s") % (q(CERT_PATH), APP_USER, q(KEY_PATH))
    return run(client, cmd, "key self-test", ok=(0, 1)) == "ok"


def apply(client, sftp, f, key_env):
    q = shlex.quote
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    undo = []

    def rollback():
        for step in reversed(undo):
            try:
                step()
            except Exception:
                pass

    try:
        python = f["python"]
        nginx_group = run(client, "id -gn %s 2>/dev/null || echo root" % q(f["nginx_user"]), "nginx group")
        if not f["user_exists"]:
            run(client, "useradd --system --no-create-home --shell /usr/sbin/nologin %s" % APP_USER, "create user")
        run(client, "mkdir -p %s/server %s/web %s/keys %s/data %s/inbox %s/backups" % ((ROOT,) * 6), "create dirs")
        run(client, ("chown root:root {r} {r}/server {r}/web && chmod 755 {r} {r}/server {r}/web && "
                     "chown root:{u} {r}/keys && chmod 750 {r}/keys && "
                     "chown {u}:{u} {r}/data {r}/inbox {r}/backups && chmod 750 {r}/data {r}/inbox {r}/backups").format(r=ROOT, u=APP_USER),
            "permissions")

        # 1. код (с копией прежнего)
        if f["installed"]:
            run(client, "mkdir -p %s/backups/code-%s && cp -a %s/server %s/web %s/backups/code-%s/" % (ROOT, stamp, ROOT, ROOT, ROOT, stamp),
                "backup of previous code")
            undo.append(lambda: run(client, "cp -a %s/backups/code-%s/server %s/backups/code-%s/web %s/ && true" % (ROOT, stamp, ROOT, stamp, ROOT),
                                    "restore code"))
        for local, remote in CODE_FILES.items():
            put(sftp, remote, (LOCAL / local).read_bytes(), 0o644)
        put(sftp, CERT_PATH, (LOCAL / "keys/entry_cert.pem").read_bytes(), 0o644)
        run(client, "chown root:%s %s && chmod 640 %s" % (APP_USER, CERT_PATH, CERT_PATH), "cert permissions")

        # 2. закрытый ключ приёма записей
        if not f["key_present"]:
            if not key_env:
                raise DeployError("STO_PRIVATE_KEY secret is required for the first installation")
            put(sftp, KEY_PATH, normalize_key(key_env).encode("ascii"), 0o600)
            run(client, "chown %s:%s %s && chmod 600 %s" % (APP_USER, APP_USER, q(KEY_PATH), q(KEY_PATH)), "key permissions")
            if not selftest_key(client):
                run(client, "rm -f %s" % q(KEY_PATH), "remove wrong key")
                raise DeployError("the private key does not match the public certificate in the repository")
            note("private key installed; self-test passed")
        elif not selftest_key(client):
            raise DeployError("the installed private key does not match the public certificate in the repository")
        else:
            note("private key already installed; self-test passed")

        # 3. логины nginx: каталог с общей группой nginx; пустой файл = вход закрыт всем
        run(client, "install -d -o %s -g %s -m 2750 %s" % (APP_USER, nginx_group, HTPASSWD_DIR), "htpasswd dir")
        if not f["htpasswd_present"]:
            run(client, "install -o %s -g %s -m 640 /dev/null %s" % (APP_USER, nginx_group, HTPASSWD), "empty htpasswd")
            note("htpasswd created empty: nobody can sign in until logins are provisioned")
        run(client, "mkdir -p /var/www/html", "acme dir")

        # 4. база и сервис
        run(client, "runuser -u %s -- %s -c \"import sys; sys.path.insert(0, '%s/server'); import store; "
            "c = store.connect('%s/data/sto.db'); store.init(c)\"" % (APP_USER, python, ROOT, ROOT), "init database")
        put(sftp, "/etc/systemd/system/" + SERVICE, service_unit(python).encode(), 0o644)
        backup_service, backup_timer = backup_units(python)
        put(sftp, "/etc/systemd/system/" + BACKUP_SERVICE, backup_service.encode(), 0o644)
        put(sftp, "/etc/systemd/system/" + BACKUP_TIMER, backup_timer.encode(), 0o644)

        def undo_systemd():
            run(client, "systemctl disable --now %s %s >/dev/null 2>&1; rm -f /etc/systemd/system/%s /etc/systemd/system/%s "
                "/etc/systemd/system/%s; systemctl daemon-reload" % (SERVICE, BACKUP_TIMER, SERVICE, BACKUP_SERVICE, BACKUP_TIMER),
                "remove units", ok=(0, 1))
        undo.append(undo_systemd)
        run(client, "systemctl daemon-reload && systemctl enable %s %s >/dev/null 2>&1 && systemctl restart %s && systemctl start %s" % (
            SERVICE, BACKUP_TIMER, SERVICE, BACKUP_TIMER), "start service")
        for _ in range(15):
            if run(client, "curl -sS --max-time 3 -o /dev/null -w '%%{http_code}' http://127.0.0.1:%d/health || true" % PORT, "health") == "200":
                break
            time.sleep(2)
        else:
            raise DeployError("service did not become healthy")
        note("service healthy on 127.0.0.1:%d" % PORT)

        # 5. nginx: новый файл, текущие не трогаем
        if f["conf_d"]:
            conf_path, link = "/etc/nginx/conf.d/sto-money.conf", None
        else:
            conf_path, link = "/etc/nginx/sites-available/sto-money", "/etc/nginx/sites-enabled/sto-money"
        put(sftp, conf_path, nginx_conf(f["cert_dir"] or None).encode(), 0o644)
        if link:
            run(client, "ln -sf %s %s" % (q(conf_path), q(link)), "enable site")

        def undo_nginx():
            run(client, "rm -f %s %s; nginx -t >/dev/null 2>&1 && nginx -s reload" % (q(conf_path), q(link or conf_path)), "remove nginx file", ok=(0, 1))
        undo.append(undo_nginx)
        run(client, "nginx -t >/dev/null 2>&1", "nginx test of the new file")
        run(client, "nginx -s reload", "nginx reload")
        if not f["cert_dir"]:
            run(client, "certbot --nginx -d %s --non-interactive --agree-tos --register-unsafely-without-email --redirect >/dev/null 2>&1" % DOMAIN,
                "certificate request", timeout=240)
            note("certificate issued for %s" % DOMAIN)
        else:
            note("existing certificate used: %s" % f["cert_dir"])
        run(client, "nginx -t >/dev/null 2>&1 && nginx -s reload", "nginx reload after certificate")

        # 6. проверка снаружи nginx: страница закрыта паролем
        codes = []
        for path in ("/", "/api/info"):
            codes.append(run(client, "curl -sk --max-time 8 --resolve %s:443:127.0.0.1 -o /dev/null -w '%%{http_code}' https://%s%s || true" % (
                DOMAIN, DOMAIN, path), "https check"))
        if codes != ["401", "401"]:
            raise DeployError("https check through nginx returned %s instead of 401 401" % "/".join(codes))
        note("https through nginx: sign-in required (401) on page and api")
        expiry = run(client, "echo | openssl s_client -connect 127.0.0.1:443 -servername %s 2>/dev/null | openssl x509 -noout -enddate" % DOMAIN,
                     "certificate expiry", ok=(0, 1))
        note("certificate " + (expiry or "expiry unknown"))
    except BaseException:
        rollback()
        raise


# ---------------------------------------------------------------- приём записей

def inbox_run(client, sftp, local_dir):
    directory = Path(local_dir)
    files = sorted(p for p in directory.glob("*.cms") if p.is_file())
    if not exists(client, ROOT + "/server/inbox.py") or not exists(client, KEY_PATH):
        raise DeployError("the service is not installed yet (run the deploy workflow first)")
    remote_names = set(sftp.listdir(ROOT + "/inbox"))
    sent = 0
    for path in files:
        if path.name not in remote_names:
            put(sftp, ROOT + "/inbox/" + path.name, path.read_bytes(), 0o640)
            sent += 1
    run(client, "chown %s:%s %s/inbox/*.cms 2>/dev/null; true" % (APP_USER, APP_USER, ROOT), "inbox permissions")
    cmd = ("runuser -u %s -- %s %s/server/inbox.py --inbox %s/inbox --key %s --db %s/data/sto.db --htpasswd %s --backup-dir %s/backups" % (
        APP_USER, run(client, "command -v python3", "python path"), ROOT, ROOT, KEY_PATH, ROOT, HTPASSWD, ROOT))
    _, stdout, _ = client.exec_command(cmd + " 2>&1", timeout=120)
    lines = [line for line in stdout.read().decode("utf-8", "replace").splitlines() if line.strip()]
    code = stdout.channel.recv_exit_status()
    note("uploaded=%d" % sent)
    for line in lines:
        # допустимые строки: «имя-файла: applied|error код» и итог; всё остальное — только как факт сбоя
        if re.fullmatch(r"[0-9A-Za-z_.-]+: (applied|error [a-z_]+)|applied=\d+ skipped=\d+ failed=\d+", line):
            note(line)
        else:
            note("unexpected output line suppressed")
    checks_failed = 0
    for path in sorted(p for p in directory.glob("*.chk") if p.is_file()):
        checks_failed += login_check(client, sftp, path)
    server_status(client)
    return 1 if (code or checks_failed) else 0


# ---------------------------------------------------------------- проверка входа и состояния (только чтение)

# Выполняется на сервере от пользователя сервиса. Файл .chk зашифрован так же, как записи: {"check_users": {логин: пароль}}.
# Пароли попадают в curl через stdin (-K -), не в аргументы процесса. Печатаются только коды ответа и да/нет.
CHECK_SCRIPT = r'''
import json, subprocess, sys
key, path, host = sys.argv[1], sys.argv[2], sys.argv[3]
out = subprocess.run(["openssl", "cms", "-decrypt", "-inform", "PEM", "-inkey", key, "-in", path], capture_output=True)
if out.returncode != 0:
    print("check decrypt: failed"); sys.exit(1)
users = json.loads(out.stdout.decode("utf-8"))["check_users"]

def get(url_path, user=None, password=None):
    config = 'user = "%s:%s"\n' % (user, password) if user else ""
    r = subprocess.run(["curl", "-sk", "--max-time", "10", "--resolve", host + ":443:127.0.0.1", "-K", "-",
                        "-w", "\n%{http_code}", "https://" + host + url_path], input=config.encode(), capture_output=True)
    body, _, status = r.stdout.decode("utf-8", "replace").rpartition("\n")
    return status.strip() or "000", body

bad = 0
status, _ = get("/")
print("check no_password: page=%s" % status); bad += status != "401"
for index, (user, password) in enumerate(sorted(users.items()), 1):
    page, html = get("/", user, password)
    info, body = get("/api/info", user, password)
    try:
        same = json.loads(body).get("user") == user
    except ValueError:
        same = False
    entries, _ = get("/api/entries?from=2026-01-01&to=2026-12-31", user, password)
    wrong, _ = get("/", user, password + "x")
    has_app = "Учёт СТО" in html
    print("check login_%d: page=%s app=%s api=%s user_match=%s entries=%s wrong_password=%s" % (
        index, page, "yes" if has_app else "no", info, "yes" if same else "no", entries, wrong))
    bad += not (page == "200" and has_app and info == "200" and same and entries == "200" and wrong == "401")
print("check result: %s" % ("ok" if not bad else "failed"))
sys.exit(1 if bad else 0)
'''
CHECK_LINE = r"check [a-z_0-9]+: [a-z_0-9=/ ]+"


def login_check(client, sftp, path):
    """Вход через nginx каждым логином из зашифрованного .chk. Возвращает 0 (всё хорошо) или 1."""
    done = ROOT + "/inbox/" + path.name + ".done"
    if exists(client, done):
        note("check %s: already done" % path.stem)
        return 0
    remote = ROOT + "/inbox/" + path.name
    put(sftp, remote, path.read_bytes(), 0o640)
    try:
        run(client, "chown %s:%s %s" % (APP_USER, APP_USER, shlex.quote(remote)), "check permissions")
        cmd = "runuser -u %s -- python3 - %s %s %s" % (APP_USER, shlex.quote(KEY_PATH), shlex.quote(remote), DOMAIN)
        stdin, stdout, _ = client.exec_command(cmd + " 2>&1", timeout=120)
        stdin.write(CHECK_SCRIPT)
        stdin.channel.shutdown_write()
        lines = [line for line in stdout.read().decode("utf-8", "replace").splitlines() if line.strip()]
        code = stdout.channel.recv_exit_status()
    finally:
        run(client, "rm -f %s" % shlex.quote(remote), "remove check file", ok=(0, 1))
    for line in lines:
        note(line if re.fullmatch(CHECK_LINE, line) else "unexpected output line suppressed")
    if code == 0:
        run(client, "touch %s" % shlex.quote(done), "mark check done")
    return 0 if code == 0 else 1


def server_status(client):
    """Факты о сервисе без данных: состояние, число логинов, копии базы, сертификат."""
    def one(command, what):
        return run(client, command + " || true", what).splitlines()[0:1] or [""]
    service = one("systemctl is-active %s" % SERVICE, "service state")[0]
    timer = one("systemctl is-active %s" % BACKUP_TIMER, "timer state")[0]
    logins = one("grep -c ':' %s" % HTPASSWD, "login count")[0]
    backups = one("ls %s/backups 2>/dev/null | grep -c '^sto-.*\\.db$'" % ROOT, "backup count")[0]
    health = one("curl -sS --max-time 3 -o /dev/null -w '%%{http_code}' http://127.0.0.1:%d/health" % PORT, "health")[0]
    cert = one("echo | openssl s_client -connect 127.0.0.1:443 -servername %s 2>/dev/null | openssl x509 -noout -enddate" % DOMAIN,
               "certificate")[0]
    note("status service=%s health=%s backup_timer=%s logins=%s db_backups=%s certificate_%s" % (
        service, health, timer, logins, backups, cert or "unknown"))


# ---------------------------------------------------------------- точка входа

def emit_report(level="notice", title="STO"):
    text = "%0A".join(line.replace("%", "%25").replace("\r", "").replace("\n", " ") for line in report) or "no output"
    print("::%s title=%s::%s" % (level, title, text))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox")
    args = parser.parse_args(argv)
    client = connect()
    sftp = client.open_sftp()
    try:
        if args.inbox:
            code = inbox_run(client, sftp, args.inbox)
            emit_report("notice" if code == 0 else "error", "STO inbox")
            return code
        facts = gather_facts(client)
        problems = blockers(facts)
        describe(facts, problems)
        if os.environ.get("APPLY", "false").lower() != "true":
            note("preflight only: nothing was changed (APPLY is not true)")
            emit_report("notice", "STO preflight")
            return 1 if problems else 0
        if problems:
            raise DeployError("blockers found; nothing was changed")
        apply(client, sftp, facts, os.environ.get("STO_PRIVATE_KEY", ""))
        note("deploy finished")
        emit_report("notice", "STO deploy")
        return 0
    except DeployError as error:
        note("ERROR: %s" % error)
        emit_report("error", "STO failed")
        return 1
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    sys.exit(main())
