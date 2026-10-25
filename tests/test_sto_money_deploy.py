"""Тесты чистой логики выкладки учёта СТО: конфигурация nginx, юниты systemd, проверка ключа, вывод в лог."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "sto_money"
sys.path.insert(0, str(ROOT))
import deploy_sto_money as d  # noqa: E402

GOOD_KEY = "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIA==\nAAAA+/==\n-----END EC PRIVATE KEY-----\n"


def facts(**over):
    base = dict(python="/usr/bin/python3", python_ok=True, openssl_cms=True, nginx="/usr/sbin/nginx", nginx_ok=True,
                conf_d=True, sites_enabled=False, nginx_user="www-data", own_conf=False, name_taken=False,
                cert_dir="servgo.ru", certbot=True, certbot_nginx=True, service_active=False, port_busy=False,
                user_exists=True, runuser=True, installed=False, key_present=False, htpasswd_present=False,
                disk_free_mb="9000")
    base.update(over)
    return base


def test_nginx_conf_with_certificate_redirects_and_protects():
    conf = d.nginx_conf("servgo.ru")
    assert "listen 443 ssl;" in conf and "return 301 https://$host$request_uri;" in conf
    assert "ssl_certificate /etc/letsencrypt/live/servgo.ru/fullchain.pem;" in conf
    assert "auth_basic_user_file /etc/nginx/sto_money/htpasswd;" in conf
    # имя пользователя берётся только из nginx и затирает значение от клиента
    assert "proxy_set_header X-Auth-User $remote_user;" in conf
    assert "$http_x_auth_user" not in conf.lower()
    assert "proxy_pass http://127.0.0.1:8095;" in conf
    # проверка домена Let's Encrypt проходит без пароля
    assert conf.count("acme-challenge") == 2 and "auth_basic off;" in conf


def test_nginx_conf_without_certificate_is_http_only_and_still_protected():
    conf = d.nginx_conf(None)
    assert "listen 443" not in conf and "ssl_certificate" not in conf
    assert 'auth_basic "STO";' in conf and "X-Auth-User $remote_user" in conf


def test_nginx_braces_balanced():
    for conf in (d.nginx_conf("x"), d.nginx_conf(None)):
        assert conf.count("{") == conf.count("}")


def test_service_unit_runs_unprivileged_and_hardened():
    unit = d.service_unit("/usr/bin/python3")
    assert "User=stomoney" in unit and "NoNewPrivileges=true" in unit and "ProtectSystem=strict" in unit
    assert "ReadWritePaths=/opt/sto_money/data" in unit and "STO_PORT=8095" in unit
    assert "ExecStart=/usr/bin/python3 /opt/sto_money/server/app.py" in unit


def test_backup_units_daily_without_deletion():
    service, timer = d.backup_units("/usr/bin/python3")
    assert "--backup-only" in service and "OnCalendar=daily" in timer
    assert "find" not in service and "rm " not in service      # копии не удаляются сами


def test_normalize_key_accepts_pem_and_fixes_line_endings():
    assert d.normalize_key(GOOD_KEY.replace("\n", "\r\n")) == GOOD_KEY
    assert d.normalize_key("  \n" + GOOD_KEY + "\n\n") == GOOD_KEY


@pytest.mark.parametrize("bad", ["", None, "hello", "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----",
                                 "-----BEGIN EC PRIVATE KEY-----\n-----END EC PRIVATE KEY-----",
                                 "-----BEGIN EC PRIVATE KEY-----\nnot base64!!\n-----END EC PRIVATE KEY-----"])
def test_normalize_key_rejects_garbage_without_echoing_it(bad):
    with pytest.raises(d.DeployError) as caught:
        d.normalize_key(bad)
    assert "not base64!!" not in str(caught.value)


def test_blockers_empty_for_healthy_server():
    assert d.blockers(facts()) == []


def test_blockers_report_each_problem():
    assert any("python3" in b for b in d.blockers(facts(python_ok=False)))
    assert any("nginx" in b for b in d.blockers(facts(nginx_ok=False)))
    assert any("conf.d" in b for b in d.blockers(facts(conf_d=False, sites_enabled=False)))
    assert any("already defined" in b for b in d.blockers(facts(name_taken=True)))
    assert any("port 8095" in b for b in d.blockers(facts(port_busy=True)))
    assert d.blockers(facts(port_busy=True, service_active=True)) == []       # порт занят нашим же сервисом
    assert any("certificate" in b for b in d.blockers(facts(cert_dir="", certbot=False)))
    assert d.blockers(facts(cert_dir="", certbot=True, certbot_nginx=True)) == []


def test_report_is_escaped_for_github_annotations(capsys):
    d.report.clear()
    d.note("line one 100% ok")
    d.note("line two")
    capsys.readouterr()
    d.emit_report("notice", "STO")
    out = capsys.readouterr().out.strip()
    assert out == "::notice title=STO::line one 100%25 ok%0Aline two"
    d.report.clear()


def test_inbox_output_whitelist_blocks_anything_unexpected():
    allowed = re.compile(r"[0-9A-Za-z_.-]+: (applied|error [a-z_]+)|applied=\d+ skipped=\d+ failed=\d+")
    for line in ("20261024T214500Z-ab12cd34: applied", "20261024T214500Z-ab12cd34: error bad_box", "applied=1 skipped=0 failed=0"):
        assert allowed.fullmatch(line)
    for line in ("Traceback (most recent call last):", "Дмитрий: 15000", "x: error bad box 15000"):
        assert not allowed.fullmatch(line)
    source = (ROOT / "deploy_sto_money.py").read_text(encoding="utf-8")
    assert allowed.pattern in source.replace("\\\\", "\\")      # тот же шаблон действительно стоит в скрипте


def test_repo_contains_only_public_cert_no_private_key():
    pems = sorted(p.name for p in (ROOT / "keys").glob("*.pem"))
    assert pems == ["entry_cert.pem"]
    assert "PRIVATE KEY" not in (ROOT / "keys" / "entry_cert.pem").read_text()


def test_login_check_script_compiles_and_output_filter_is_strict():
    compile(d.CHECK_SCRIPT, "check", "exec")
    for line in ("check no_password: page=401", "check result: ok",
                 "check login_1: page=200 app=yes api=200 user_match=yes entries=200 wrong_password=401"):
        assert re.fullmatch(d.CHECK_LINE, line)
    for line in ("check login_1: artur Kp7mNx4Z", "Traceback (most recent call last):", "check x: 15 000 ₽"):
        assert not re.fullmatch(d.CHECK_LINE, line)
    # пароль уходит в curl только через stdin, не через аргументы
    assert '"-K", "-"' in d.CHECK_SCRIPT and "-u" not in d.CHECK_SCRIPT.split("subprocess.run([\"curl\"")[1].split("]")[0]
