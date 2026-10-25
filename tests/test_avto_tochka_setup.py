import importlib.util
from datetime import date
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "configure_avto_tochka", Path(__file__).resolve().parents[1] / "scripts" / "configure_avto_tochka.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def test_days_off_cover_two_weeks_with_agreed_weekdays():
    plan = setup.plan_days_off(date(2026, 10, 25), 14)  # 25 Oct 2026 is a Sunday
    assert [d.isoformat() for d in plan['Павел']] == ['2026-10-25', '2026-11-01']
    assert [d.isoformat() for d in plan['Дмитрий']] == ['2026-10-25', '2026-10-26', '2026-11-01', '2026-11-02']
    assert [d.isoformat() for d in plan['Сослан']] == ['2026-10-31', '2026-11-07']
    assert [d.isoformat() for d in plan['Алексей']] == ['2026-10-27', '2026-11-03']
    assert [d.isoformat() for d in plan['Илья']] == [
        '2026-10-29', '2026-10-30', '2026-11-05', '2026-11-06']
    assert all(date(2026, 10, 25) <= d <= date(2026, 11, 7) for dates in plan.values() for d in dates)


def test_price_list_matches_owner_numbers():
    prices = {name: price for name, price, _ in setup.SERVICES}
    assert list(prices.values()) == [1700, 2500, 2500, 3500, 2000, 3000, 2500, 5000]
    assert len(prices) == len(setup.SERVICES)  # names are unique


def test_every_variant_explains_who_it_is_for():
    for name, _, text in setup.SERVICES:
        assert text.strip() and len(text) > 40
        assert name.startswith('Сход-развал')
        assert setup.GENERIC_NOTE.strip() in setup.service_description(text)
