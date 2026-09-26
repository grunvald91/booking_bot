"""The demo offers one five-hour booking with a concrete price per vessel."""
import unittest

from scripts.configure_100boats_demo_db import DEMO_HOURS, VESSEL_RATES, demo_total


class DemoPriceTest(unittest.TestCase):
    def test_five_hour_demo_totals(self):
        self.assertEqual(DEMO_HOURS, 5)
        self.assertEqual(len(VESSEL_RATES), 9)
        self.assertEqual(demo_total('Princess 45'), 95000)
        self.assertEqual(demo_total('Sunseeker 72'), 295000)
        self.assertEqual(demo_total('Bavaria 380 Sport'), 60000)

    def test_unknown_vessel_is_not_given_a_made_up_price(self):
        with self.assertRaises(KeyError):
            demo_total('Unknown vessel')


if __name__ == '__main__':
    unittest.main()
