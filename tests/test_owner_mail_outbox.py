"""Outbox shows what was sent so the owner can read it and write again."""
import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from web.api.routes import owner_mail


def test_outbox_returns_subject_and_text_for_direct_and_campaign_mail(tmp_path, monkeypatch):
    data = tmp_path / "mail"
    data.mkdir(mode=0o700)
    monkeypatch.setenv("SERVGO_MAIL_DATA_DIR", str(data))
    with owner_mail.db_open() as db:
        db.execute("INSERT INTO prospects (id,company,email,website,notes) VALUES ('p1','Мята','hi@mint.ru','','')")
        db.execute("INSERT INTO drafts (prospect_id,subject,body,reviewed,state) VALUES ('p1','Тема А','Текст А',1,'smtp_accepted')")
        db.execute("INSERT INTO deliveries (id,prospect_id,status,created_at) VALUES ('d1','p1','smtp_accepted','2026-10-17T10:00:00')")
        db.execute("INSERT INTO direct_mail (id,email,subject,body,status,created_at) VALUES "
                   "('m1','x@y.ru','Тема Б','Текст Б','delivery_unknown','2026-10-18T10:00:00')")
    rows = owner_mail.outbox(None)
    assert [(r["email"], r["subject"], r["body"], r["status"]) for r in rows] == [
        ("x@y.ru", "Тема Б", "Текст Б", "delivery_unknown"),
        ("hi@mint.ru", "Тема А", "Текст А", "smtp_accepted"),
    ]


def test_outbox_tab_offers_compose_and_write_again():
    page = (owner_mail.Path(owner_mail.__file__).parent / "owner_mail_ui.html").read_text(encoding="utf-8")
    assert 'id="list-compose"' in page and "Написать ещё раз" in page and "openCompose(" in page
