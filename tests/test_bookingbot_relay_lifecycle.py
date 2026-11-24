"""Regression contract for BookingBot's relay service dependency."""
import ast
import configparser
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RelayLifecycleTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((ROOT / "scripts/deploy_bot_relay89.py").read_text())
        assignments = [
            node.value for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "DROPIN_TEXT"
                    for t in node.targets)
        ]
        self.assertEqual(len(assignments), 1)
        self.unit = configparser.ConfigParser(interpolation=None)
        self.unit.read_string(ast.literal_eval(assignments[0]))

    def test_relay_failure_does_not_stop_bookingbot(self):
        self.assertIn("booking-bot-relay89.service", self.unit["Unit"]["Wants"].split())
        self.assertIn("booking-bot-relay89.service", self.unit["Unit"]["After"].split())
        for dependency in ("Requires", "BindsTo", "PartOf"):
            self.assertNotIn("booking-bot-relay89.service",
                             self.unit["Unit"].get(dependency, "").split())

    def test_restarts_are_paced_and_not_permanently_locked_out(self):
        self.assertEqual(self.unit["Unit"]["StartLimitIntervalSec"], "0")
        self.assertEqual(self.unit["Service"]["Restart"], "always")
        self.assertEqual(self.unit["Service"]["RestartSec"], "20s")

    def test_existing_private_telegram_route_is_preserved(self):
        self.assertEqual(self.unit["Service"]["Environment"],
                         "BOT_PROXY_URL=socks5://127.0.0.1:1089")


if __name__ == "__main__":
    unittest.main()
