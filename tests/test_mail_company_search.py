"""2GIS company search: reading its pages, stopping when refused, loading results into a campaign."""
import asyncio
import json
import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import httpx
import pytest

from web.api.routes import mail_company_search as search
from web.api.routes import owner_mail
from web.api.routes.mail_campaign_api import CampaignInput, create_campaign
from web.api.routes.mail_campaign_store import initialize as init_campaigns


def page(state):
    """A page shaped like the real one: the data sits in `initialState = JSON.parse('...')`."""
    raw = json.dumps(state, ensure_ascii=False).replace("\\", "\\\\").replace("'", "\\'")
    return "<html><script>var __x = 1; var initialState = JSON.parse('" + raw + "');</script></html>"


def profile(firm_id, name, rubrics=("Салоны красоты",), contacts=None, rating=4.8):
    data = {"id": firm_id, "name": name, "address_name": "улица Роз, 1", "reviews": {"general_rating": rating},
            "rubrics": [{"name": r, "kind": "primary"} for r in rubrics]}
    if contacts is not None:
        data["contact_groups"] = [{"contacts": contacts}]
    return {"data": data, "meta": {"code": 200}}


def search_page(ids, firms, current=1, pages=1, total=None):
    return page({"data": {
        "entity": {"profile": {i: profile(i, firms[i]) for i in ids}},
        "search": {"profile": {"q": {"data": {"pages": pages, "total": total or len(ids), "currentPage": current}}},
                   "pagination": {"q": {str(current): {"data": list(ids), "meta": {"code": 200}}}}}}})


def firm_page(firm_id, name, contacts, rubrics=("Салоны красоты",)):
    return page({"data": {"entity": {"profile": {firm_id: profile(firm_id, name, rubrics, contacts)}}}})


CONTACTS_FULL = [
    {"type": "phone", "value": "+78620000001", "text": "+7 (862) 000-00-01"},
    {"type": "website", "url": "http://www.mint-studio.ru/booking?utm_source=2gis&utm_medium=cpc&a=1",
     "value": "http://link.2gis.ru/1.2/x?http://www.mint-studio.ru/"},
    {"type": "email", "value": "Hello@Mint-Studio.ru", "text": "hello@mint-studio.ru"},
    {"type": "telegram", "value": "https://t.me/mint_studio"},
    {"type": "whatsapp", "value": "https://wa.me/78620000001"},
]


def test_search_page_gives_ids_names_and_page_count():
    html = search_page(["1", "2"], {"1": "Мята", "2": "Лотос"}, pages=24, total=285)
    found = search.parse_search_page(html, 1)
    assert found.ids == ["1", "2"] and found.pages == 24 and found.total == 285
    assert found.firms["1"] == {"name": "Мята", "address": "улица Роз, 1", "rubrics": ["Салоны красоты"], "rating": 4.8}


def test_firm_page_gives_contacts_with_a_clean_https_site():
    card = search.parse_firm_page(firm_page("1", "Мята", CONTACTS_FULL), "1")
    assert card["phones"] == ["+78620000001"]
    assert card["email"] == "hello@mint-studio.ru"
    assert card["website"] == "https://www.mint-studio.ru/booking?a=1"
    assert card["telegram"] == "https://t.me/mint_studio" and card["whatsapp"] == "https://wa.me/78620000001"
    assert search.parse_firm_page(firm_page("1", "Мята", []), "1")["email"] == ""
    assert search.parse_firm_page(firm_page("1", "Мята", []), "other") is None


def test_page_without_data_is_treated_as_a_refusal():
    with pytest.raises(search.Blocked):
        search.parse_search_page("<html>Проверка, что вы не робот</html>", 1)
    with pytest.raises(search.Blocked):
        search.parse_firm_page("<html></html>", "1")


def test_email_found_in_site_text_and_city_names():
    assert search.email_from_site_text("Пишите: Info@Salon.ru, тел. 123") == "info@salon.ru"
    assert search.email_from_site_text("logo@2x.png и ничего больше") == ""
    assert search.city_slug("Сочи") == "sochi" and search.city_slug("moscow") == "moscow"
    with pytest.raises(search.HTTPException):
        search.city_slug("Неизвестный город")
    assert search.search_url("sochi", "салон красоты", 3) == "https://2gis.ru/sochi/search/%D1%81%D0%B0%D0%BB%D0%BE%D0%BD%20%D0%BA%D1%80%D0%B0%D1%81%D0%BE%D1%82%D1%8B/page/3"


class FakeClient:
    """Serves prepared pages by URL. An exception value is raised, like a dropped connection."""
    routes: dict = {}
    asked: list = []

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        FakeClient.asked.append(url)
        answer = FakeClient.routes.get(url, (404, ""))
        if isinstance(answer, Exception):
            raise answer
        return type("R", (), {"status_code": answer[0], "text": answer[1]})()


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "mail"
    data.mkdir(mode=0o700)
    monkeypatch.setenv("SERVGO_MAIL_DATA_DIR", str(data))
    monkeypatch.setenv("SERVGO_SEARCH_PAUSE_SECONDS", "0")
    monkeypatch.setattr(search.httpx, "AsyncClient", FakeClient)
    FakeClient.routes, FakeClient.asked = {}, []

    async def fake_hub(prompt):
        return {"fit": "Мята" in prompt or "Лотос" in prompt, "reason": "запись на услугу"}

    async def no_site(url):
        return {"excerpt": ""}

    monkeypatch.setattr(search, "hub", fake_hub)
    monkeypatch.setattr(search, "research_public_site", lambda url: {"excerpt": "Пишите на booking@lotos.ru"})
    return FakeClient


def new_job(want=None):
    with owner_mail.db_open() as db:
        search.initialize(db)
        db.execute("INSERT INTO search_job (id,niche,city,want,status,created_at,updated_at) VALUES "
                   "('j1','салон','sochi',?,'running','t','t')", (want,))


def serve_two_firms(client):
    client.routes[search.search_url("sochi", "салон", 1)] = (200, search_page(
        ["1", "2", "3"], {"1": "Мята", "2": "Лотос", "3": "Магазин шин"}))
    client.routes[search.firm_url("sochi", "1")] = (200, firm_page("1", "Мята", CONTACTS_FULL))
    client.routes[search.firm_url("sochi", "2")] = (200, firm_page(
        "2", "Лотос", [{"type": "website", "url": "https://lotos.ru/"}]))
    client.routes[search.firm_url("sochi", "3")] = (200, firm_page(
        "3", "Магазин шин", [{"type": "phone", "value": "+78620000009"}], rubrics=("Шины",)))


def test_search_collects_cards_finds_email_on_site_and_marks_fit(env):
    serve_two_firms(env)
    new_job()
    asyncio.run(search.run_job("j1", "салон", "sochi", None))
    with owner_mail.db_open() as db:
        view = search._view(db, "j1")
    assert view["job"]["status"] == "done"
    by_name = {h["name"]: h for h in view["hits"]}
    assert by_name["Мята"]["email"] == "hello@mint-studio.ru" and by_name["Мята"]["email_source"] == "2ГИС"
    assert by_name["Лотос"]["email"] == "booking@lotos.ru" and by_name["Лотос"]["email_source"] == "сайт"
    assert by_name["Магазин шин"]["email"] == "" and by_name["Магазин шин"]["fit"] == 0
    assert view["counts"] == {"found": 3, "with_email": 2, "fit": 2, "ready": 2}


def test_search_stops_when_enough_companies_with_email_are_found(env):
    serve_two_firms(env)
    new_job(want=1)
    asyncio.run(search.run_job("j1", "салон", "sochi", 1))
    with owner_mail.db_open() as db:
        view = search._view(db, "j1")
    assert view["job"]["status"] == "done" and len(view["hits"]) == 1
    assert search.firm_url("sochi", "2") not in env.asked


def test_refusal_stops_the_search_keeps_results_and_does_not_retry(env):
    serve_two_firms(env)
    env.routes[search.firm_url("sochi", "2")] = httpx.ReadError("connection reset")
    new_job()
    asyncio.run(search.run_job("j1", "салон", "sochi", None))
    with owner_mail.db_open() as db:
        view = search._view(db, "j1")
    assert view["job"]["status"] == "blocked" and "оборвал" in view["job"]["message"]
    assert [h["name"] for h in view["hits"]] == ["Мята"]
    assert env.asked.count(search.firm_url("sochi", "2")) == 1
    assert search.firm_url("sochi", "3") not in env.asked


def test_http_429_is_a_refusal_too(env):
    env.routes[search.search_url("sochi", "салон", 1)] = (429, "")
    new_job()
    asyncio.run(search.run_job("j1", "салон", "sochi", None))
    with owner_mail.db_open() as db:
        assert search._view(db, "j1")["job"]["status"] == "blocked"


def test_second_page_is_read_when_there_are_more_pages(env):
    env.routes[search.search_url("sochi", "салон", 1)] = (200, search_page(["1"], {"1": "Мята"}, pages=2, total=2))
    env.routes[search.search_url("sochi", "салон", 2)] = (200, search_page(["2"], {"2": "Лотос"}, current=2, pages=2, total=2))
    env.routes[search.firm_url("sochi", "1")] = (200, firm_page("1", "Мята", CONTACTS_FULL))
    env.routes[search.firm_url("sochi", "2")] = (200, firm_page("2", "Лотос", [{"type": "email", "value": "a@lotos.ru"}]))
    new_job()
    asyncio.run(search.run_job("j1", "салон", "sochi", None))
    with owner_mail.db_open() as db:
        view = search._view(db, "j1")
    assert view["job"]["status"] == "done" and view["job"]["pages_total"] == 2
    assert {h["name"] for h in view["hits"]} == {"Мята", "Лотос"}


def test_fit_companies_with_email_go_into_a_campaign_once(env):
    serve_two_firms(env)
    new_job()
    asyncio.run(search.run_job("j1", "салон", "sochi", None))
    with owner_mail.db_open() as db:
        init_campaigns(db)
    campaign_id = create_campaign(CampaignInput(name="Салоны Сочи"), None)["id"]
    first = search.to_campaign("j1", search.ToCampaign(campaign_id=campaign_id), None)
    assert first["selected"] == 2 and first["added"] == 2
    again = search.to_campaign("j1", search.ToCampaign(campaign_id=campaign_id), None)
    assert again["selected"] == 0
    with owner_mail.db_open() as db:
        rows = db.execute("SELECT email,company,website,notes,status FROM campaign_recipient ORDER BY email").fetchall()
    assert [r["email"] for r in rows] == ["booking@lotos.ru", "hello@mint-studio.ru"]
    mint = next(r for r in rows if r["company"] == "Мята")
    assert mint["website"] == "https://www.mint-studio.ru/booking?a=1"
    assert "2ГИС" in mint["notes"] and "Салоны красоты" in mint["notes"] and "+78620000001" in mint["notes"]


def test_a_search_that_died_with_the_service_is_shown_as_interrupted(env):
    new_job()
    with owner_mail.db_open() as db:
        view = search._view(db, "j1")
    assert view["job"]["status"] == "interrupted"
