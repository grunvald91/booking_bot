"""Offline campaign tests. SMTP and ClaudeHub are always mocked."""
import sqlite3
from contextlib import contextmanager

import pytest

from web.api.routes import (
    mail_campaign_api as api,
    mail_campaign_review as review,
    mail_campaign_dispatch as dispatch,
    mail_campaign_research as research,
    mail_campaign_store as store,
)


@pytest.fixture
def memory_mail(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    @contextmanager
    def fake_database():
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    for module in (api, review, dispatch, research):
        monkeypatch.setattr(module, "db_open", fake_database)
    store.initialize(connection)
    yield connection
    connection.close()


def fixture_campaign():
    created = api.create_campaign(api.CampaignInput(name="Test ServGo"), _=object())
    cid = created["id"]
    data = api.RecipientList(recipients=[
        api.RecipientInput(email="team@example.com", company="Test Studio"),
        api.RecipientInput(email="TEAM@example.com"),
        api.RecipientInput(email="bad-address"),
    ])
    summary = api.add_recipients(cid, data, _=object())
    return cid, summary


def test_import_deduplicates_and_tracks_invalid(memory_mail):
    cid, result = fixture_campaign()
    assert result == {"added": 1, "duplicates": 1, "invalid": 1, "excluded": 0}
    details = api.campaign_detail(cid, _=object())
    assert details["metrics"]["total"] == 1
    assert details["recipients"][0]["email"] == "team@example.com"


def test_approval_requires_review_and_send_not_automatic(memory_mail):
    cid, _ = fixture_campaign()
    rid = api.campaign_detail(cid, _=object())["recipients"][0]["id"]
    with pytest.raises(Exception):
        review.approve(cid, review.ReviewSelection(recipient_ids=[rid]), _=object())
    memory_mail.execute(
        "UPDATE campaign_recipient SET status='review',subject=?,body=? WHERE id=?",
        ("Предложение ServGo", "Здравствуйте! Посмотрите сервис для записи клиентов.", rid),
    )
    assert review.approve(
        cid, review.ReviewSelection(recipient_ids=[rid]), _=object()
    )["approved"] == 1
    assert review.launch(
        cid, review.CampaignLaunch(start_at=None), _=object()
    )["status"] == "running"
    assert store.summary(memory_mail, cid)["smtp_accepted"] == 0


@pytest.mark.asyncio
async def test_one_smtp_acceptance_no_duplicate(memory_mail, monkeypatch):
    cid, _ = fixture_campaign()
    rid = api.campaign_detail(cid, _=object())["recipients"][0]["id"]
    memory_mail.execute(
        "UPDATE campaign_recipient SET status='approved',subject=?,body=? WHERE id=?",
        ("О ServGo", "Здравствуйте! Готовы показать онлайн-запись вашего бизнеса.", rid),
    )
    review.launch(cid, review.CampaignLaunch(start_at=None), _=object())
    monkeypatch.setenv("SERVGO_MAIL_FROM", "info@servgo.ru")
    monkeypatch.setattr(dispatch, "sign", lambda *a, **kw: "test-token")
    sent = []
    monkeypatch.setattr(dispatch, "send_local_smtp",
                        lambda msg, sender, recipient: sent.append(recipient))
    assert await dispatch.dispatch_one() is True
    assert await dispatch.dispatch_one() is False
    assert sent == ["team@example.com"]
    assert store.summary(memory_mail, cid)["smtp_accepted"] == 1


@pytest.mark.asyncio
async def test_uncertain_smtp_response_is_not_retried(memory_mail, monkeypatch):
    cid, _ = fixture_campaign()
    rid = api.campaign_detail(cid, _=object())["recipients"][0]["id"]
    memory_mail.execute(
        "UPDATE campaign_recipient SET status='approved',subject=?,body=? WHERE id=?",
        ("О ServGo", "Здравствуйте! Готовы показать онлайн-запись вашего бизнеса.", rid),
    )
    review.launch(cid, review.CampaignLaunch(start_at=None), _=object())
    monkeypatch.setenv("SERVGO_MAIL_FROM", "info@servgo.ru")
    monkeypatch.setattr(dispatch, "sign", lambda *a, **kw: "test-token")
    def timeout(*args):
        raise TimeoutError("Fake timeout")
    monkeypatch.setattr(dispatch, "send_local_smtp", timeout)
    assert await dispatch.dispatch_one() is True
    assert await dispatch.dispatch_one() is False
    assert store.summary(memory_mail, cid)["delivery_unknown"] == 1


@pytest.mark.asyncio
async def test_personalized_draft_requires_review(memory_mail, monkeypatch):
    cid, _ = fixture_campaign()
    review.prepare(cid, _=object())
    monkeypatch.setattr(research, "research_public_site",
                        lambda _: {"excerpt": "", "status": "No website"})
    calls = []
    async def fake_hub(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return {"subject": "О ServGo",
                    "body": "Здравствуйте! Предлагаем посмотреть онлайн-запись для вашего бизнеса."}
        return {"critical": False, "reason": ""}
    monkeypatch.setattr(research, "hub", fake_hub)
    assert await research.prepare_one() is True
    row = api.campaign_detail(cid, _=object())["recipients"][0]
    assert row["status"] == "review"
    assert len(calls) == 2
