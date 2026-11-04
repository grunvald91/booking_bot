"""Yandex Mail requires explicit storage entitlement; no live API spend in tests."""
import pytest
from fastapi import HTTPException
from web.api.routes import mail_company_search as m


@pytest.mark.asyncio
async def test_yandex_provider_hidden_without_storage_rights(monkeypatch):
    async def cap(_path):
        return {"enabled": True, "storage_allowed": False}
    monkeypatch.setattr(m, "studio_get", cap)
    assert (await m.providers(None))["yandex"] is False
    with pytest.raises(HTTPException) as err:
        await m.start(m.SearchInput(niche="салоны красоты", city="Сочи", provider="yandex"), None)
    assert err.value.status_code == 503


@pytest.mark.asyncio
async def test_yandex_provider_visible_only_with_license_and_storage(monkeypatch):
    async def cap(_path):
        return {"enabled": True, "storage_allowed": True}
    monkeypatch.setattr(m, "studio_get", cap)
    assert (await m.providers(None))["yandex"] is True


def test_yandex_supported_as_explicit_source():
    assert m.SearchInput(niche="автосервис", provider="yandex").provider == "yandex"
    assert m.SearchInput(niche="автосервис").provider == "2gis"
