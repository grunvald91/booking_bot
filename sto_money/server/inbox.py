"""Приём зашифрованных записей: расшифровка закрытым ключом сервера и применение к базе.

Каждый файл inbox/*.cms — одно сообщение {"ops": [...]}, зашифрованное открытым ключом (OpenSSL CMS).
В вывод попадают только имена файлов и короткие коды: вывод виден в публичном логе Actions,
суммы, имена боксов и пароли не печатаются никогда.

  python3 inbox.py --inbox DIR --key KEY.pem --db DB --htpasswd FILE [--backup-dir DIR]
  python3 inbox.py --db DB --backup-dir DIR --backup-only
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store  # noqa: E402


def decrypt(path, key_path):
    """Расшифрованный текст сообщения (bytes). Ошибка расшифровки — ValidationError('decrypt_failed')."""
    result = subprocess.run(["openssl", "cms", "-decrypt", "-inform", "PEM", "-inkey", key_path, "-in", path],
                            capture_output=True, timeout=60)
    if result.returncode != 0 or not result.stdout:
        raise store.ValidationError("decrypt_failed")
    return result.stdout


def hash_password(password):
    """Хэш apr1 для nginx; пароль передаётся через stdin, а не в аргументах процесса."""
    result = subprocess.run(["openssl", "passwd", "-apr1", "-stdin"], input=password.encode("utf-8"),
                            capture_output=True, timeout=30)
    line = result.stdout.decode("utf-8").strip()
    if result.returncode != 0 or not line.startswith("$apr1$"):
        raise RuntimeError("password hash failed")
    return line


def write_htpasswd(users, path):
    """Полностью заменяет файл логинов nginx. Каталог с setgid отдаёт файлу группу nginx."""
    lines = "".join("%s:%s\n" % (name, hash_password(password)) for name, password in sorted(users.items()))
    directory = os.path.dirname(path) or "."
    fd, temp = tempfile.mkstemp(prefix=".htpasswd-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(lines)
        os.chmod(temp, 0o640)
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise


def backup_db(db_path, backup_dir):
    os.makedirs(backup_dir, exist_ok=True)
    dest = os.path.join(backup_dir, "sto-%s.db" % time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    conn = store.connect(db_path)
    try:
        store.backup(conn, dest)
    finally:
        conn.close()
    return dest


def process(inbox_dir, key_path, db_path, htpasswd_path, backup_dir=None):
    """Возвращает (применено, пропущено, ошибок)."""
    names = sorted(name for name in os.listdir(inbox_dir) if name.endswith(".cms"))
    conn = store.connect(db_path)
    store.init(conn)
    applied = skipped = failed = 0
    try:
        pending = [name for name in names if not store.is_applied(conn, name[:-4])]
        if pending and backup_dir:
            backup_db(db_path, backup_dir)
        skipped = len(names) - len(pending)
        for name in pending:
            stem = name[:-4]
            try:
                message = json.loads(decrypt(os.path.join(inbox_dir, name), key_path).decode("utf-8"))
                handlers = {"set_users": lambda op: write_htpasswd(op["users"], htpasswd_path)}
                store.apply_message(conn, stem, message, handlers=handlers)
                applied += 1
                print("%s: applied" % stem)
            except store.ValidationError as error:
                store.mark_failed(conn, stem, error.code)
                failed += 1
                print("%s: error %s" % (stem, error.code))
            except (UnicodeDecodeError, ValueError):
                store.mark_failed(conn, stem, "bad_json")
                failed += 1
                print("%s: error bad_json" % stem)
    finally:
        conn.close()
    return applied, skipped, failed


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox")
    parser.add_argument("--key")
    parser.add_argument("--db", required=True)
    parser.add_argument("--htpasswd")
    parser.add_argument("--backup-dir")
    parser.add_argument("--backup-only", action="store_true")
    args = parser.parse_args(argv)
    if args.backup_only:
        if not args.backup_dir:
            parser.error("--backup-dir is required")
        backup_db(args.db, args.backup_dir)
        print("backup: ok")
        return 0
    if not (args.inbox and args.key and args.htpasswd):
        parser.error("--inbox, --key and --htpasswd are required")
    applied, skipped, failed = process(args.inbox, args.key, args.db, args.htpasswd, args.backup_dir)
    print("applied=%d skipped=%d failed=%d" % (applied, skipped, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
