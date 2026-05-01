import unittest
from datetime import date, timedelta

from database import crud


class BookingSafetyTests(unittest.TestCase):
    def test_lock_dates_cover_neighboring_days_in_stable_order(self):
        booking_date = date(2026, 5, 1)

        self.assertEqual(
            crud._booking_lock_dates(booking_date),
            [
                booking_date - timedelta(days=1),
                booking_date,
                booking_date + timedelta(days=1),
            ],
        )

    def test_lock_params_use_employee_id_and_date_ordinal(self):
        booking_date = date(2026, 5, 1)

        self.assertEqual(
            crud._booking_day_lock_params(12, booking_date),
            {"employee_id": 12, "day_key": booking_date.toordinal()},
        )

    def test_active_booking_statuses_include_prepayment_holds(self):
        self.assertIn("pending", crud.ACTIVE_BOOKING_STATUSES)
        self.assertIn("confirmed", crud.ACTIVE_BOOKING_STATUSES)
        self.assertIn("pending_prepayment", crud.ACTIVE_BOOKING_STATUSES)
        self.assertIn("prepayment_sent", crud.ACTIVE_BOOKING_STATUSES)

    def test_client_duplicate_statuses_include_prepayment_flow(self):
        self.assertIn("pending_prepayment", crud.CLIENT_DUPLICATE_STATUSES)
        self.assertIn("prepayment_sent", crud.CLIENT_DUPLICATE_STATUSES)


if __name__ == "__main__":
    unittest.main()
