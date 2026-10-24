"""Хранилище учёта выручки по бокам СТО: SQLite, только стандартная библиотека.

Одна запись = один бокс за один день: всего, наличные, на карту, терминал.
Ошибки проверки несут короткий код без данных: его безопасно печатать в публичный лог Actions.
"""
import datetime
import json
import re
import sqlite3

BOXES = ("Дмитрий", "Алексей", "Илья", "Сослан")
PARTS = ("cash", "card", "terminal")
FIELDS = ("total",) + PARTS
USER_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
MIN_PASSWORD = 8

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    date TEXT NOT NULL,
    box TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    cash INTEGER NOT NULL DEFAULT 0,
    card INTEGER NOT NULL DEFAULT 0,
    terminal INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    PRIMARY KEY (date, box)
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    user TEXT NOT NULL,
    action TEXT NOT NULL,
    date TEXT NOT NULL,
    box TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT
);
CREATE TABLE IF NOT EXISTS applied (
    name TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    status TEXT NOT NULL
);
"""


class ValidationError(ValueError):
    """code — короткий код ошибки без данных (bad_date, bad_box, bad_amount, bad_field, bad_op, bad_users...)."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def connect(path):
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def backup(conn, dest_path):
    """Согласованная копия базы (безопасна при работающем сервисе)."""
    target = sqlite3.connect(dest_path)
    try:
        conn.backup(target)
    finally:
        target.close()


# ---------------------------------------------------------------- проверка значений

def check_date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValidationError("bad_date")
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        raise ValidationError("bad_date") from None
    return value


def check_box(value):
    if value not in BOXES:
        raise ValidationError("bad_box")
    return value


def check_amount(value):
    """Целое число рублей. Ограничений по величине нет, только тип (и предел 64-битного хранилища)."""
    if isinstance(value, bool):
        raise ValidationError("bad_amount")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int) or abs(value) >= 2 ** 62:
        raise ValidationError("bad_amount")
    return value


def check_users(users):
    if not isinstance(users, dict) or not users:
        raise ValidationError("bad_users")
    for name, password in users.items():
        if not isinstance(name, str) or not USER_RE.match(name):
            raise ValidationError("bad_users")
        if (not isinstance(password, str) or len(password) < MIN_PASSWORD
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in password)):
            raise ValidationError("bad_users")
    return users


def check_op(op):
    """Проверяет операцию целиком, ничего не записывая. Возвращает её вид."""
    if not isinstance(op, dict):
        raise ValidationError("bad_op")
    kind = op.get("op")
    if kind == "set":
        check_date(op.get("date"))
        check_box(op.get("box"))
        if set(op) - set(FIELDS) - {"op", "date", "box"}:
            raise ValidationError("bad_field")
        values = [op[key] for key in FIELDS if key in op]
        if not values:
            raise ValidationError("bad_op")
        for value in values:
            check_amount(value)
    elif kind == "delete":
        check_date(op.get("date"))
        check_box(op.get("box"))
        if set(op) - {"op", "date", "box"}:
            raise ValidationError("bad_field")
    elif kind == "set_users":
        if set(op) - {"op", "users"}:
            raise ValidationError("bad_field")
        check_users(op.get("users"))
    else:
        raise ValidationError("bad_op")
    return kind


# ---------------------------------------------------------------- записи

def _row(conn, date, box):
    found = conn.execute("SELECT * FROM entries WHERE date=? AND box=?", (date, box)).fetchone()
    return dict(found) if found else None


def _public(row):
    return {key: row[key] for key in ("date", "box") + FIELDS + ("updated_at", "updated_by")}


def _log(conn, user, action, date, box, old, new, now):
    conn.execute(
        "INSERT INTO history(ts, user, action, date, box, old_value, new_value) VALUES (?,?,?,?,?,?,?)",
        (now, user, action, date, box,
         json.dumps({k: old[k] for k in FIELDS}) if old else None,
         json.dumps({k: new[k] for k in FIELDS}) if new else None))


def set_entry(conn, date, box, values, user, now=None):
    """Задаёт указанные поля записи; остальные остаются как были (у новой записи — нули).

    Если «всего» не указано, оно считается суммой трёх способов оплаты.
    Транзакцию (commit) открывает и закрывает вызывающий.
    """
    check_date(date)
    check_box(box)
    if not isinstance(values, dict) or not values:
        raise ValidationError("bad_op")
    if set(values) - set(FIELDS):
        raise ValidationError("bad_field")
    given = {key: check_amount(value) for key, value in values.items()}
    now = now or utc_now()
    old = _row(conn, date, box)
    new = {key: (old[key] if old else 0) for key in FIELDS}
    new.update(given)
    if "total" not in given:
        new["total"] = sum(new[part] for part in PARTS)
    conn.execute(
        "INSERT INTO entries(date, box, total, cash, card, terminal, updated_at, updated_by) VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(date, box) DO UPDATE SET total=excluded.total, cash=excluded.cash, card=excluded.card, "
        "terminal=excluded.terminal, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
        (date, box, new["total"], new["cash"], new["card"], new["terminal"], now, user))
    _log(conn, user, "set", date, box, old, new, now)
    return _public(_row(conn, date, box))


def delete_entry(conn, date, box, user, now=None):
    check_date(date)
    check_box(box)
    old = _row(conn, date, box)
    if not old:
        return False
    conn.execute("DELETE FROM entries WHERE date=? AND box=?", (date, box))
    _log(conn, user, "delete", date, box, old, None, now or utc_now())
    return True


def list_entries(conn, start, end):
    check_date(start)
    check_date(end)
    rows = conn.execute("SELECT * FROM entries WHERE date>=? AND date<=? ORDER BY date", (start, end)).fetchall()
    order = {name: index for index, name in enumerate(BOXES)}
    result = [_public(dict(row)) for row in rows]
    result.sort(key=lambda item: (item["date"], order.get(item["box"], 99)))
    return result


def history(conn, limit=100):
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValidationError("bad_limit")
    rows = conn.execute("SELECT ts, user, action, date, box, old_value, new_value FROM history "
                        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["old"] = json.loads(item.pop("old_value")) if item["old_value"] else None
        item["new"] = json.loads(item.pop("new_value")) if item["new_value"] else None
        result.append(item)
    return result


# ---------------------------------------------------------------- приём сообщений из inbox

def is_applied(conn, name):
    return conn.execute("SELECT 1 FROM applied WHERE name=?", (name,)).fetchone() is not None


def mark_failed(conn, name, code):
    with conn:
        conn.execute("INSERT OR IGNORE INTO applied(name, ts, status) VALUES (?,?,?)", (name, utc_now(), "error:" + code))


def apply_message(conn, name, message, user="диктовка", handlers=None, now=None):
    """Применяет сообщение {"ops": [...]} целиком или не применяет вовсе. Повторное применение — пропуск.

    handlers: {"set_users": функция(op)} — операции вне базы; выполняются после записей базы
    внутри той же транзакции, поэтому при их сбое база откатывается.
    Возвращает "applied" или "skipped".
    """
    if is_applied(conn, name):
        return "skipped"
    if not isinstance(message, dict) or not isinstance(message.get("ops"), list) or not message["ops"]:
        raise ValidationError("bad_message")
    ops = message["ops"]
    kinds = [check_op(op) for op in ops]
    handlers = handlers or {}
    if any(kind == "set_users" and "set_users" not in handlers for kind in kinds):
        raise ValidationError("bad_op")
    now = now or utc_now()
    with conn:
        for op, kind in zip(ops, kinds):
            if kind == "set":
                set_entry(conn, op["date"], op["box"], {key: op[key] for key in FIELDS if key in op}, user, now)
            elif kind == "delete":
                delete_entry(conn, op["date"], op["box"], user, now)
        for op, kind in zip(ops, kinds):
            if kind == "set_users":
                handlers["set_users"](op)
        conn.execute("INSERT INTO applied(name, ts, status) VALUES (?,?,?)", (name, now, "ok"))
    return "applied"
