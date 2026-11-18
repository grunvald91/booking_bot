"""Offline contract tests for the guarded production bot username patch."""
import unittest
from scripts.ops.servgo_bot_username_release import rewrite_username

class BotUsernameTests(unittest.TestCase):
    def test_rewrite_scope(self):
        before = b"BOT_TOKEN=sensitive-test-value\nBOT_USERNAME='Sochiservice_bot'\nDB_NAME=servgo\n"
        after, changed = rewrite_username(before)
        self.assertTrue(changed)
        self.assertEqual(after, b"BOT_TOKEN=sensitive-test-value\nBOT_USERNAME='sochi_servgo_bot'\nDB_NAME=servgo\n")

    def test_idempotence(self):
        before = b'BOT_USERNAME="sochi_servgo_bot"\n'
        self.assertEqual(rewrite_username(before), (before, False))

    def test_reject_unsafe(self):
        for before in (b"BOT_TOKEN=x\n", b"BOT_USERNAME=old_bot\n",
                       b"BOT_USERNAME=$(cat /secret)\n",
                       b"BOT_USERNAME=Sochiservice_bot\nBOT_USERNAME=sochi_servgo_bot\n"):
            with self.subTest(before=before):
                with self.assertRaises(RuntimeError):
                    rewrite_username(before)

    def test_preserve_crlf(self):
        self.assertEqual(rewrite_username(b"BOT_USERNAME=Sochiservice_bot\r\nX=1\r\n"),
                         (b"BOT_USERNAME=sochi_servgo_bot\r\nX=1\r\n", True))

if __name__ == "__main__":
    unittest.main()
