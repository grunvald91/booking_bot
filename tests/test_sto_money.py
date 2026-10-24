"""Тесты учёта выручки по бокам СТО: суммы, проверка данных, шифрованная диктовка, вход и API."""
import http.client
import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "sto_money"
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tools"))
import app  # noqa: E402
import encrypt_entry  # noqa: E402
import inbox  # noqa: E402
import store  # noqa: E402


@pytest.fixture()
def conn(tmp_path):
    connection = store.connect(str(tmp_path / "t.db"))
    store.init(connection)
    yield connection
    connection.close()


@pytest.fixture()
def keys(tmp_path):
    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(key)],
                   check=True, capture_output=True)
    subprocess.run(["openssl", "req", "-new", "-x509", "-key", str(key), "-days", "30", "-subj", "/CN=t",
                    "-addext", "keyUsage=keyAgreement", "-out", str(cert)], check=True, capture_output=True)
    return str(key), str(cert)


def entry(**kw):
    return {"op": "set", "date": "2026-10-24", "box": "Дмитрий", **kw}


# ---------------------------------------------------------------- записи и суммы

def test_set_entry_total_is_sum_of_parts_when_not_given(conn):
    with conn:
        row = store.set_entry(conn, "2026-10-24", "Дмитрий", {"cash": 5000, "card": 6000, "terminal": 4000}, "artur")
    assert (row["total"], row["cash"], row["card"], row["terminal"]) == (15000, 5000, 6000, 4000)


def test_set_entry_partial_update_keeps_other_fields(conn):
    with conn:
        store.set_entry(conn, "2026-10-24", "Илья", {"total": 10000, "cash": 4000, "card": 6000}, "artur")
        row = store.set_entry(conn, "2026-10-24", "Илья", {"terminal": 500}, "artur")
    # «всего» не указано — пересчитано из трёх частей
    assert (row["cash"], row["card"], row["terminal"], row["total"]) == (4000, 6000, 500, 10500)


def test_total_given_alone_keeps_parts_zero_so_page_can_flag_mismatch(conn):
    with conn:
        row = store.set_entry(conn, "2026-10-24", "Алексей", {"total": 12000}, "artur")
    assert row["total"] == 12000 and row["cash"] == row["card"] == row["terminal"] == 0


def test_no_limits_on_amounts_only_type_is_checked(conn):
    with conn:
        row = store.set_entry(conn, "2026-10-24", "Сослан", {"total": 99999999, "cash": -500}, "artur")
    assert row["total"] == 99999999 and row["cash"] == -500


@pytest.mark.parametrize("bad", ["12", "1e3", 12.5, None, True, [1], {"a": 1}])
def test_amount_must_be_integer(conn, bad):
    with pytest.raises(store.ValidationError) as caught:
        store.set_entry(conn, "2026-10-24", "Дмитрий", {"total": bad}, "artur")
    assert caught.value.code == "bad_amount"


def test_integral_float_is_accepted(conn):
    with conn:
        assert store.set_entry(conn, "2026-10-24", "Дмитрий", {"total": 1000.0}, "artur")["total"] == 1000


@pytest.mark.parametrize("date", ["2026-13-01", "2026-02-30", "24.10.2026", "", None, 20261024])
def test_bad_date_rejected(conn, date):
    with pytest.raises(store.ValidationError) as caught:
        store.set_entry(conn, date, "Дмитрий", {"total": 1}, "artur")
    assert caught.value.code == "bad_date"


def test_unknown_box_and_field_rejected(conn):
    with pytest.raises(store.ValidationError) as caught:
        store.set_entry(conn, "2026-10-24", "Иван", {"total": 1}, "artur")
    assert caught.value.code == "bad_box"
    with pytest.raises(store.ValidationError) as caught:
        store.set_entry(conn, "2026-10-24", "Дмитрий", {"tips": 1}, "artur")
    assert caught.value.code == "bad_field"


def test_list_entries_range_and_box_order(conn):
    with conn:
        for box in ("Сослан", "Дмитрий", "Илья", "Алексей"):
            store.set_entry(conn, "2026-10-02", box, {"total": 1}, "a")
        store.set_entry(conn, "2026-09-30", "Дмитрий", {"total": 1}, "a")
        store.set_entry(conn, "2026-11-01", "Дмитрий", {"total": 1}, "a")
    rows = store.list_entries(conn, "2026-10-01", "2026-10-31")
    assert [r["box"] for r in rows] == ["Дмитрий", "Алексей", "Илья", "Сослан"]


def test_delete_and_history_record_who_and_what(conn):
    with conn:
        store.set_entry(conn, "2026-10-24", "Дмитрий", {"total": 100}, "artur")
        store.set_entry(conn, "2026-10-24", "Дмитрий", {"total": 150}, "aleksandr")
        assert store.delete_entry(conn, "2026-10-24", "Дмитрий", "artur") is True
        assert store.delete_entry(conn, "2026-10-24", "Дмитрий", "artur") is False
    log = store.history(conn, 10)
    assert [(h["user"], h["action"]) for h in log] == [("artur", "delete"), ("aleksandr", "set"), ("artur", "set")]
    assert log[1]["old"]["total"] == 100 and log[1]["new"]["total"] == 150
    assert store.list_entries(conn, "2026-10-01", "2026-10-31") == []


# ---------------------------------------------------------------- сообщения: всё или ничего, повтор безопасен

def test_message_is_atomic_and_idempotent(conn):
    good = entry(total=100)
    with pytest.raises(store.ValidationError):
        store.apply_message(conn, "m1", {"ops": [good, entry(box="Нет такого", total=1)]})
    assert store.list_entries(conn, "2026-10-01", "2026-10-31") == []       # ничего не применилось
    assert store.apply_message(conn, "m2", {"ops": [good]}) == "applied"
    assert store.apply_message(conn, "m2", {"ops": [entry(total=999)]}) == "skipped"
    assert store.list_entries(conn, "2026-10-01", "2026-10-31")[0]["total"] == 100


def test_handler_failure_rolls_back_database(conn):
    def boom(op):
        raise OSError("disk")
    with pytest.raises(OSError):
        store.apply_message(conn, "m3", {"ops": [entry(total=5), {"op": "set_users", "users": {"artur": "Abcdefg2"}}]},
                            handlers={"set_users": boom})
    assert store.list_entries(conn, "2026-10-01", "2026-10-31") == []
    assert not store.is_applied(conn, "m3")


@pytest.mark.parametrize("users", [{}, {"Artur": "Abcdefg2"}, {"artur": "short"}, {"artur": "ab\ncdefgh"}, {"a": "Abcdefg2"}, "x"])
def test_users_validation(users):
    with pytest.raises(store.ValidationError) as caught:
        store.check_op({"op": "set_users", "users": users})
    assert caught.value.code == "bad_users"


# ---------------------------------------------------------------- шифрованная диктовка

def test_encrypted_roundtrip_applies_and_second_run_skips(tmp_path, keys, capsys):
    key, cert = keys
    inbox_dir, db = tmp_path / "inbox", tmp_path / "s.db"
    encrypt_entry.encrypt(json.dumps({"ops": [entry(total=15000, cash=5000, card=6000, terminal=4000)]}), cert, str(inbox_dir))
    htpasswd = tmp_path / "htpasswd"
    assert inbox.process(str(inbox_dir), key, str(db), str(htpasswd), str(tmp_path / "bk")) == (1, 0, 0)
    conn = store.connect(str(db))
    assert store.list_entries(conn, "2026-10-01", "2026-10-31")[0]["total"] == 15000
    assert store.history(conn, 1)[0]["user"] == "диктовка"
    conn.close()
    assert inbox.process(str(inbox_dir), key, str(db), str(htpasswd), str(tmp_path / "bk")) == (0, 1, 0)


def test_ciphertext_does_not_contain_data_and_output_has_no_amounts(tmp_path, keys, capsys):
    key, cert = keys
    path = encrypt_entry.encrypt(json.dumps({"ops": [entry(total=777123)]}), cert, str(tmp_path / "in"))
    raw = Path(path).read_bytes()
    assert b"777123" not in raw and "Дмитрий".encode() not in raw
    inbox.process(str(tmp_path / "in"), key, str(tmp_path / "s.db"), str(tmp_path / "h"))
    out = capsys.readouterr().out
    assert "777123" not in out and "Дмитрий" not in out


def test_wrong_key_is_permanent_error_without_leak(tmp_path, keys, capsys):
    _, cert = keys
    other = tmp_path / "other.pem"
    subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(other)], check=True,
                   capture_output=True)
    encrypt_entry.encrypt(json.dumps({"ops": [entry(total=1)]}), cert, str(tmp_path / "in"))
    assert inbox.process(str(tmp_path / "in"), str(other), str(tmp_path / "s.db"), str(tmp_path / "h")) == (0, 0, 1)
    assert "decrypt_failed" in capsys.readouterr().out
    # повторный запуск не пытается снова: ошибка запомнена
    assert inbox.process(str(tmp_path / "in"), str(other), str(tmp_path / "s.db"), str(tmp_path / "h")) == (0, 1, 0)


def test_encrypt_tool_refuses_invalid_data(tmp_path, keys):
    _, cert = keys
    with pytest.raises(store.ValidationError):
        encrypt_entry.encrypt(json.dumps({"ops": [entry(box="Иван", total=1)]}), cert, str(tmp_path / "in"))
    assert not (tmp_path / "in").exists() or not list((tmp_path / "in").iterdir())


def test_set_users_writes_apr1_htpasswd_with_secure_mode(tmp_path, keys):
    key, cert = keys
    encrypt_entry.encrypt(json.dumps({"ops": [{"op": "set_users", "users": {"artur": "Kp7mNx4Z", "aleksandr": "Wq3tRh9B"}}]}),
                          cert, str(tmp_path / "in"))
    htpasswd = tmp_path / "ht" / "htpasswd"
    htpasswd.parent.mkdir()
    assert inbox.process(str(tmp_path / "in"), key, str(tmp_path / "s.db"), str(htpasswd)) == (1, 0, 0)
    lines = dict(line.split(":", 1) for line in htpasswd.read_text().splitlines())
    assert set(lines) == {"artur", "aleksandr"}
    for user, password in (("artur", "Kp7mNx4Z"), ("aleksandr", "Wq3tRh9B")):
        salt = lines[user].split("$")[2]
        check = subprocess.run(["openssl", "passwd", "-apr1", "-salt", salt, "-stdin"], input=password.encode(),
                               capture_output=True).stdout.decode().strip()
        assert check == lines[user]
    assert oct(htpasswd.stat().st_mode & 0o777) == "0o640"
    assert "Kp7mNx4Z" not in htpasswd.read_text()


def test_backup_only_makes_copy(tmp_path):
    db = tmp_path / "s.db"
    connection = store.connect(str(db))
    store.init(connection)
    with connection:
        store.set_entry(connection, "2026-10-24", "Дмитрий", {"total": 5}, "a")
    connection.close()
    assert inbox.main(["--db", str(db), "--backup-dir", str(tmp_path / "bk"), "--backup-only"]) == 0
    copy = next((tmp_path / "bk").iterdir())
    copied = store.connect(str(copy))
    assert copied.execute("SELECT total FROM entries").fetchone()[0] == 5
    copied.close()


# ---------------------------------------------------------------- HTTP API

@pytest.fixture()
def server(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
    db = str(tmp_path / "api.db")
    conn = store.connect(db)
    store.init(conn)
    conn.close()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler(db, str(web)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()


def call(port, method, path, body=None, user="artur", content_type="application/json"):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {}
    if user:
        headers["X-Auth-User"] = user
    if body is not None:
        headers["Content-Type"] = content_type
    connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response.status, (json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw)


def test_api_put_list_delete_roundtrip(server):
    status, body = call(server, "PUT", "/api/entry", {"date": "2026-10-24", "box": "Дмитрий", "total": 15000,
                                                      "cash": 5000, "card": 6000, "terminal": 4000})
    assert status == 200 and body["entry"]["updated_by"] == "artur"
    status, body = call(server, "GET", "/api/entries?from=2026-10-01&to=2026-10-31")
    assert status == 200 and body["entries"][0]["terminal"] == 4000
    assert call(server, "DELETE", "/api/entry?date=2026-10-24&box=%D0%94%D0%BC%D0%B8%D1%82%D1%80%D0%B8%D0%B9")[1] == {"removed": True}
    assert call(server, "GET", "/api/entries?from=2026-10-01&to=2026-10-31")[1]["entries"] == []
    status, body = call(server, "GET", "/api/history?limit=5")
    assert status == 200 and [h["action"] for h in body["history"]] == ["delete", "set"]


def test_api_writes_need_user_header_and_json_content_type(server):
    payload = {"date": "2026-10-24", "box": "Дмитрий", "total": 1}
    assert call(server, "PUT", "/api/entry", payload, user=None)[0] == 403
    assert call(server, "DELETE", "/api/entry?date=2026-10-24&box=x", user=None)[0] == 403
    status, body = call(server, "PUT", "/api/entry", payload, content_type="text/plain")
    assert status == 400 and body["error"] == "bad_content_type"


def test_api_rejects_bad_data_with_codes(server):
    status, body = call(server, "PUT", "/api/entry", {"date": "2026-10-24", "box": "Дмитрий", "total": "5"})
    assert (status, body["error"]) == (400, "bad_amount")
    status, body = call(server, "PUT", "/api/entry", {"date": "2026-10-24", "box": "Дмитрий", "total": 5, "x": 1})
    assert (status, body["error"]) == (400, "bad_field")
    assert call(server, "GET", "/api/entries?from=bad&to=2026-10-31")[1]["error"] == "bad_date"
    assert call(server, "GET", "/nope")[0] == 404


def test_page_is_served_with_security_headers(server):
    connection = http.client.HTTPConnection("127.0.0.1", server, timeout=5)
    connection.request("GET", "/")
    response = connection.getresponse()
    response.read()
    assert response.status == 200
    assert "frame-ancestors 'none'" in response.getheader("Content-Security-Policy")
    assert response.getheader("X-Robots-Tag").startswith("noindex")
    connection.close()
    assert call(server, "GET", "/health")[1] == {"ok": True}
