"""Offline check of the mail.servgo.ru login: stub DB and stub Growth, no network, no SMTP.

Run: python test_mail_login.py   (needs fastapi, httpx, python-jose, sqlalchemy, aiosqlite)
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(tempfile.mkdtemp())
pkg = ROOT / "web" / "api" / "routes"
pkg.mkdir(parents=True)
for p in (ROOT / "web", ROOT / "web" / "api", pkg):
    (p / "__init__.py").write_text("")
(ROOT / "web" / "api" / "database.py").write_text('''
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
Base = declarative_base()
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, nullable=True)
engine = create_async_engine("sqlite+aiosqlite:///" + __import__("os").environ["TEST_DB"])
Session = async_sessionmaker(engine, expire_on_commit=False)
async def get_db():
    async with Session() as s:
        yield s
''')
(ROOT / "web" / "api" / "deps.py").write_text("def get_current_user():\n    raise RuntimeError('not used')\n")
shutil.copy(HERE / "owner_mail.py", pkg / "owner_mail.py")
shutil.copy(HERE / "mail_campaign_ui.py", pkg / "mail_campaign_ui.py")
(pkg / "mail_campaign_dashboard.html").write_text("<html>DASHBOARD</html>")
(pkg / "owner_mail_ui.html").write_text("<html>MAILBOX</html>")

data_dir = ROOT / "data"
data_dir.mkdir(mode=0o700)
os.environ.update(TEST_DB=str(ROOT / "t.db"), SERVGO_MAIL_SESSION_SECRET="x" * 40,
                  SERVGO_MAIL_OWNER_USER_ID="7", SERVGO_MAIL_DATA_DIR=str(data_dir))
sys.path.insert(0, str(ROOT))

import asyncio  # noqa: E402
import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from web.api import database  # noqa: E402
from web.api.routes import mail_campaign_ui, owner_mail  # noqa: E402


async def setup_db():
    async with database.engine.begin() as conn:
        await conn.run_sync(database.Base.metadata.create_all)
    async with database.Session() as s:
        s.add(database.User(id=7))
        await s.commit()
asyncio.run(setup_db())

GROWTH = {"mode": "ok", "calls": []}
REAL_CLIENT = httpx.AsyncClient


def growth(request):
    GROWTH["calls"].append(request.url.path)
    if GROWTH["mode"] == "down":
        raise httpx.ConnectError("down")
    auth = request.headers.get("authorization", "")
    import base64
    ok = auth == "Basic " + base64.b64encode(b"artur:right-pass").decode()
    return httpx.Response(200 if ok else 401)


owner_mail.httpx.AsyncClient = lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(growth), **kw)

app = FastAPI()
app.include_router(owner_mail.router)
app.include_router(mail_campaign_ui.router)
ORIGIN = {"Origin": "https://mail.servgo.ru"}


def device():
    return TestClient(app, base_url="https://mail.servgo.ru")


def login(c, user, pw, headers=ORIGIN, ip="1.1.1.1"):
    return c.post("/owner-mail/api/login", json={"username": user, "password": pw},
                  headers={**headers, "X-Real-IP": ip})


phone1, phone2 = device(), device()

r = phone1.get("/owner-mail/app")
assert r.status_code == 200 and 'type="password"' in r.text and "Войти" in r.text, r.text[:200]
assert phone1.get("/owner-mail/api/campaigns-dashboard", follow_redirects=False).headers["location"] == "/"

assert login(phone1, "artur", "right-pass", headers={"Origin": "https://evil.example"}).status_code == 403
GROWTH["calls"].clear()
assert login(phone1, "someone", "right-pass").status_code == 401
assert GROWTH["calls"] == [], "unknown login must not reach Growth"
assert login(phone1, "artur", "wrong").status_code == 401

assert login(device(), "Artur", "right-pass", ip="5.5.5.5").status_code == 200
assert login(device(), " Артур ", "right-pass", ip="6.6.6.6").status_code == 200
r = login(phone1, "artur", "right-pass")
assert r.status_code == 200, r.text
cookie = r.headers["set-cookie"].lower()
assert "samesite=lax" in cookie and "max-age=2592000" in cookie and "httponly" in cookie and "secure" in cookie, cookie
assert "DASHBOARD" in phone1.get("/owner-mail/app").text
assert "MAILBOX" in phone1.get("/owner-mail/api/mailbox-dashboard").text

assert login(phone2, "artur", "right-pass", ip="2.2.2.2").status_code == 200
assert "DASHBOARD" in phone2.get("/owner-mail/app").text
assert "DASHBOARD" in phone1.get("/owner-mail/app").text, "second device must not log out the first"

assert phone1.post("/owner-mail/api/prospects", json={"company": "Ab", "email": "a@b.ru"},
                   headers={"Origin": "https://evil.example"}).status_code == 403

r = phone1.get("/owner-mail/api/logout", follow_redirects=False)
assert r.status_code == 303 and "servgo_owner_mail=" in r.headers["set-cookie"]
phone1.cookies.clear()
assert 'type="password"' in phone1.get("/owner-mail/app").text

attacker = device()
for _ in range(8):
    assert login(attacker, "artur", "guess", ip="9.9.9.9").status_code == 401
assert login(attacker, "artur", "right-pass", ip="9.9.9.9").status_code == 429
assert login(device(), "artur", "right-pass", ip="3.3.3.3").status_code == 200, "lockout is per address"

GROWTH["mode"] = "down"
assert login(device(), "artur", "right-pass", ip="4.4.4.4").status_code == 503
print("mail login: all checks passed")
