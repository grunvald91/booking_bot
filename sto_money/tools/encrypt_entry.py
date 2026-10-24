"""Шифрует набор операций открытым ключом и кладёт файл в inbox. Содержимое не печатается.

Вход (stdin или --json): {"ops": [{"op": "set", "date": "2026-10-24", "box": "Дмитрий",
"total": 15000, "cash": 5000, "card": 6000, "terminal": 4000}, {"op": "delete", ...}, ...]}

  python3 sto_money/tools/encrypt_entry.py --inbox sto_money/inbox [--cert sto_money/keys/entry_cert.pem]
Печатает путь созданного файла. Расшифровать его может только закрытый ключ на сервере.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))
import store  # noqa: E402

DEFAULT_CERT = os.path.join(os.path.dirname(HERE), "keys", "entry_cert.pem")


def encrypt(payload, cert_path, inbox_dir):
    message = json.loads(payload)
    if not isinstance(message, dict) or not isinstance(message.get("ops"), list) or not message["ops"]:
        raise store.ValidationError("bad_message")
    for op in message["ops"]:
        store.check_op(op)
    name = "%s-%s.cms" % (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:8])
    path = os.path.join(inbox_dir, name)
    os.makedirs(inbox_dir, exist_ok=True)
    result = subprocess.run(["openssl", "cms", "-encrypt", "-aes-256-cbc", "-outform", "PEM", "-recip", cert_path,
                             "-out", path], input=json.dumps(message, ensure_ascii=False).encode("utf-8"),
                            capture_output=True, timeout=60)
    if result.returncode != 0 or not os.path.exists(path):
        raise RuntimeError("encrypt failed")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cert", default=DEFAULT_CERT)
    parser.add_argument("--inbox", required=True)
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    payload = args.json if args.json is not None else sys.stdin.read()
    try:
        print(encrypt(payload, args.cert, args.inbox))
    except (store.ValidationError, ValueError) as error:
        print("error: %s" % getattr(error, "code", "bad_json"), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
