"""Fail CI if a Telegram-style bot token is embedded in source text.

Only file paths and line numbers are printed; matched secret contents are never
written to logs.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_RE = re.compile(r"(?<!\d)\d{7,12}:[A-Za-z0-9_-]{30,}(?![A-Za-z0-9_-])")
TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yml", ".yaml",
    ".toml", ".ini", ".cfg", ".md", ".sql", ".sh",
}
SKIP_PARTS = {".git", "node_modules", "dist", ".venv", "venv"}

findings: list[tuple[str, int]] = []
for path in ROOT.rglob("*"):
    if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
        continue
    if any(part in SKIP_PARTS for part in path.parts):
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for line_no, line in enumerate(text.splitlines(), start=1):
        if TOKEN_RE.search(line):
            findings.append((str(path.relative_to(ROOT)), line_no))

if findings:
    print("Embedded Telegram-style secrets found:")
    for path, line_no in findings:
        print(f"- {path}:{line_no}")
    raise SystemExit(1)

print("embedded_telegram_tokens=0")
