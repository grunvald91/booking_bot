"""Regression guard: Telegram bot tokens must come from the environment only."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_RE = re.compile(rb"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")


def test_no_telegram_bot_tokens_in_tracked_files():
    files = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout.split(b"\0")
    offenders = []
    for name in filter(None, files):
        path = ROOT / name.decode()
        if not path.is_file():
            continue
        if TOKEN_RE.search(path.read_bytes()):
            offenders.append(name.decode())
    assert not offenders, f"Hardcoded Telegram bot token found in: {offenders}"


if __name__ == "__main__":
    test_no_telegram_bot_tokens_in_tracked_files()
    print("ok")
