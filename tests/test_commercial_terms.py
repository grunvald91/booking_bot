"""Smoke tests for user-visible ServGo commercial terms."""

import unittest

from bot.services.commercial_terms import format_commercial_terms
from webapp.niches import get_offer


class CommercialTermsTest(unittest.TestCase):
    def test_bot_uses_current_site_prices(self):
        offer = get_offer()
        message = format_commercial_terms(offer)
        self.assertIn(offer["entry_price_text"], message)
        self.assertIn(offer["studio_price_text"], message)
        self.assertIn(str(offer["seats_total"]), message)
        self.assertIn("подключение бесплатно", message)
        self.assertIn("в месяц", message)
        self.assertIn("один раз", message)

    def test_prices_are_not_hard_coded(self):
        message = format_commercial_terms({
            "entry_price_text": "1 234 ₽",
            "studio_price_text": "4 567 ₽",
            "seats_total": 2,
        })
        self.assertIn("1 234 ₽", message)
        self.assertIn("4 567 ₽", message)
        self.assertIn("Первые 2 бизнеса", message)

    def test_html_is_escaped(self):
        message = format_commercial_terms({
            "entry_price_text": "<script>",
            "studio_price_text": "<b>1</b>",
            "seats_total": 1,
        })
        self.assertNotIn("<script>", message)
        self.assertIn("&lt;script&gt;", message)
        self.assertIn("&lt;b&gt;1&lt;/b&gt;", message)

    def test_invalid_free_seats_fails_closed(self):
        with self.assertRaises(ValueError):
            format_commercial_terms({
                "entry_price_text": "990 ₽",
                "studio_price_text": "2 990 ₽",
                "seats_total": 0,
            })


if __name__ == "__main__":
    unittest.main()
