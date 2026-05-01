import unittest
from datetime import time
from types import SimpleNamespace

from bot.utils.business_readiness import build_business_readiness_warnings


def business(**kwargs):
    defaults = {
        "business_type": "salon",
        "phone": "+79990000000",
        "address": "Москва",
        "working_hours_start": time(9, 0),
        "working_hours_end": time(18, 0),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class BusinessReadinessTests(unittest.TestCase):
    def test_complete_service_business_has_no_warnings(self):
        warnings = build_business_readiness_warnings(
            business(),
            services=[SimpleNamespace(name="Стрижка")],
            workers=[SimpleNamespace(name="Анна")],
        )

        self.assertEqual(warnings, [])

    def test_missing_core_setup_is_reported_for_service_business(self):
        warnings = build_business_readiness_warnings(
            business(phone=None, address=None, working_hours_start=None),
            services=[],
            workers=[],
        )

        self.assertIn("Добавьте хотя бы одну услугу", warnings)
        self.assertIn("Добавьте хотя бы одного сотрудника/мастера", warnings)
        self.assertIn("Укажите телефон для связи", warnings)
        self.assertIn("Укажите адрес", warnings)
        self.assertIn("Укажите время работы", warnings)

    def test_venue_business_uses_room_wording(self):
        warnings = build_business_readiness_warnings(
            business(business_type="venue_rental"),
            services=[],
            workers=[],
        )

        self.assertIn("Добавьте хотя бы один вариант времени аренды", warnings)
        self.assertIn("Добавьте хотя бы одно помещение/зал", warnings)


if __name__ == "__main__":
    unittest.main()
