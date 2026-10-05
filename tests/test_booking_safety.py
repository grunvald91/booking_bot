from datetime import datetime
from types import SimpleNamespace
import unittest

from database.booking_safety import (
    booking_resource_duration,
    intervals_overlap,
    service_occupies_resource,
)


class BookingSafetyUnitTests(unittest.TestCase):
    def test_same_interval_overlaps(self):
        start = datetime(2026, 10, 6, 10, 0)
        end = datetime(2026, 10, 6, 11, 0)
        self.assertTrue(intervals_overlap(start, end, start, end))

    def test_partial_overlap_is_rejected(self):
        self.assertTrue(
            intervals_overlap(
                datetime(2026, 10, 6, 10, 30),
                datetime(2026, 10, 6, 11, 30),
                datetime(2026, 10, 6, 10, 0),
                datetime(2026, 10, 6, 11, 0),
            )
        )

    def test_touching_intervals_do_not_overlap(self):
        self.assertFalse(
            intervals_overlap(
                datetime(2026, 10, 6, 11, 0),
                datetime(2026, 10, 6, 12, 0),
                datetime(2026, 10, 6, 10, 0),
                datetime(2026, 10, 6, 11, 0),
            )
        )

    def test_cross_midnight_overlap(self):
        self.assertTrue(
            intervals_overlap(
                datetime(2026, 10, 7, 0, 15),
                datetime(2026, 10, 7, 1, 0),
                datetime(2026, 10, 6, 23, 30),
                datetime(2026, 10, 7, 0, 30),
            )
        )

    def test_additional_service_does_not_occupy_resource(self):
        service = SimpleNamespace(is_additional=True, duration_minutes=60)
        self.assertFalse(service_occupies_resource(service))

    def test_main_zero_duration_does_not_occupy_resource(self):
        service = SimpleNamespace(is_additional=False, duration_minutes=0)
        self.assertFalse(service_occupies_resource(service))

    def test_duration_snapshot_wins_over_live_service_duration(self):
        booking = SimpleNamespace(
            resource_duration_minutes=45,
            duration_minutes=None,
            service=SimpleNamespace(duration_minutes=90),
        )
        self.assertEqual(booking_resource_duration(booking), 45)

    def test_legacy_rental_duration_fallback(self):
        booking = SimpleNamespace(
            resource_duration_minutes=None,
            duration_minutes=180,
            service=SimpleNamespace(duration_minutes=60),
        )
        self.assertEqual(booking_resource_duration(booking), 180)


if __name__ == "__main__":
    unittest.main()
