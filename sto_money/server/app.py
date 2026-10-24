"""Сервис учёта выручки по бокам СТО (sto.servgo.ru).

Слушает только 127.0.0.1; вход по логину и паролю делает nginx и передаёт имя в заголовке X-Auth-User.
Записи без этого заголовка не принимаются. Тела запросов не логируются.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
             "font-src https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
             "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
MAX_BODY = 64 * 1024  # технический предел размера тела запроса


def make_handler(db_path, web_dir):
    class Handler(BaseHTTPRequestHandler):
        server_version = "sto-money"
        sys_version = ""

        # ------------------------------------------------ вспомогательное
        def log_message(self, fmt, *args):  # путь без тела; без IP-адресов клиентов
            sys.stderr.write("%s %s\n" % (self.command, urlparse(self.path).path))

        def _send(self, status, body, content_type, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            self.send_header("Referrer-Policy", "no-referrer")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})

        def _user(self):
            return (self.headers.get("X-Auth-User") or "").strip()[:64]

        def _conn(self):
            conn = store.connect(db_path)
            store.init(conn)
            return conn

        def _body(self):
            if "application/json" not in (self.headers.get("Content-Type") or "").lower():
                raise store.ValidationError("bad_content_type")
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                raise store.ValidationError("bad_body") from None
            if length <= 0 or length > MAX_BODY:
                raise store.ValidationError("bad_body")
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise store.ValidationError("bad_body") from None
            if not isinstance(data, dict):
                raise store.ValidationError("bad_body")
            return data

        def _guard_write(self):
            if not self._user():
                self._json(403, {"error": "no_user"})
                return False
            return True

        # ------------------------------------------------ маршруты
        def do_GET(self):
            url = urlparse(self.path)
            query = {key: values[0] for key, values in parse_qs(url.query).items()}
            try:
                if url.path in ("/", "/index.html"):
                    with open(os.path.join(web_dir, "index.html"), "rb") as handle:
                        page = handle.read()
                    self._send(200, page, "text/html; charset=utf-8",
                               {"Cache-Control": "no-store", "Content-Security-Policy": INDEX_CSP})
                elif url.path == "/health":
                    conn = self._conn()
                    conn.execute("SELECT 1").fetchone()
                    conn.close()
                    self._json(200, {"ok": True})
                elif url.path == "/api/info":
                    self._json(200, {"boxes": list(store.BOXES), "user": self._user()})
                elif url.path == "/api/entries":
                    conn = self._conn()
                    try:
                        self._json(200, {"entries": store.list_entries(conn, query.get("from", ""), query.get("to", ""))})
                    finally:
                        conn.close()
                elif url.path == "/api/history":
                    conn = self._conn()
                    try:
                        limit = int(query.get("limit", "100"))
                        self._json(200, {"history": store.history(conn, limit)})
                    except ValueError:
                        raise store.ValidationError("bad_limit") from None
                    finally:
                        conn.close()
                else:
                    self._json(404, {"error": "not_found"})
            except store.ValidationError as error:
                self._json(400, {"error": error.code})
            except FileNotFoundError:
                self._json(500, {"error": "no_page"})

        def do_PUT(self):
            url = urlparse(self.path)
            if url.path != "/api/entry":
                return self._json(404, {"error": "not_found"})
            if not self._guard_write():
                return
            try:
                data = self._body()
                values = {key: data[key] for key in store.FIELDS if key in data}
                if set(data) - set(store.FIELDS) - {"date", "box"}:
                    raise store.ValidationError("bad_field")
                conn = self._conn()
                try:
                    with conn:
                        entry = store.set_entry(conn, data.get("date"), data.get("box"), values, self._user())
                finally:
                    conn.close()
                self._json(200, {"entry": entry})
            except store.ValidationError as error:
                self._json(400, {"error": error.code})

        def do_DELETE(self):
            url = urlparse(self.path)
            if url.path != "/api/entry":
                return self._json(404, {"error": "not_found"})
            if not self._guard_write():
                return
            query = {key: values[0] for key, values in parse_qs(url.query).items()}
            try:
                conn = self._conn()
                try:
                    with conn:
                        removed = store.delete_entry(conn, query.get("date"), query.get("box"), self._user())
                finally:
                    conn.close()
                self._json(200, {"removed": removed})
            except store.ValidationError as error:
                self._json(400, {"error": error.code})

    return Handler


def serve(db_path, web_dir, host="127.0.0.1", port=8095):
    conn = store.connect(db_path)
    store.init(conn)
    conn.close()
    server = ThreadingHTTPServer((host, port), make_handler(db_path, web_dir))
    server.serve_forever()


if __name__ == "__main__":
    serve(os.environ.get("STO_DB", "/opt/sto_money/data/sto.db"),
          os.environ.get("STO_WEB", os.path.join(os.path.dirname(HERE), "web")),
          os.environ.get("STO_HOST", "127.0.0.1"),
          int(os.environ.get("STO_PORT", "8095")))
