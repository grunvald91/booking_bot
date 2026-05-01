from pathlib import Path
import unittest


LANDING_HTML = Path("webapp/templates/landing.html")


class LandingPageTests(unittest.TestCase):
    def test_landing_mentions_core_business_value(self):
        html = LANDING_HTML.read_text(encoding="utf-8")

        self.assertIn("ServGo", html)
        self.assertIn("без хаоса в чатах", html)
        self.assertIn("владелец дает данные", html)
        self.assertIn("защита от двойной записи", html)

    def test_landing_does_not_name_competing_products(self):
        html = LANDING_HTML.read_text(encoding="utf-8").lower()

        forbidden_names = [
            "yclients",
            "yclients",
            "yclients",
            "юclients",
            "сонлайн",
            "dikidi",
            "dikidi",
        ]
        for name in forbidden_names:
            self.assertNotIn(name, html)


if __name__ == "__main__":
    unittest.main()
