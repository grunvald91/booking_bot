"""Bring three outdated source copies on the server up to the version in main (GitHub -> server).

Only files whose server copy is provably an OLDER revision of the same file in git are replaced; a server copy that is
unique (a hotfix) or unreadable is never touched. Each replaced file is backed up next to itself first, written through
a temporary file, and checked by hash afterwards. No service is restarted: these are source files that nothing loads
(the seed script is run by hand; the front-end sources only matter at the next build).
Usage: refresh_stale_server_copies.py [--apply]   (without --apply nothing on the server changes)
"""
import hashlib
import sys
import time
from pathlib import Path

from sync_server_source import ROOT, classify, connect, history_hashes

FILES = (
    "scripts/seed_100boats_demo.py",
    "web/frontend/src/components/AdminShell.tsx",
    "web/frontend/src/components/OwnerMailEntry.tsx",
)


def decide(kind: str) -> str:
    """replace | keep | refuse: only a copy that is just behind git may be replaced."""
    return {"behind": "replace", "same": "keep"}.get(kind, "refuse")


def main(apply: bool) -> int:
    ssh = connect()
    sftp = ssh.open_sftp()
    stamp = str(int(time.time()))
    failed = 0
    try:
        for path in FILES:
            repo = Path(path).read_bytes()
            try:
                with sftp.open(ROOT + path, "rb") as handle:
                    server = handle.read()
            except FileNotFoundError:
                print(f"{path}: not on the server; skipped")
                continue
            kind = classify(path, server, repo, history_hashes(path) if server != repo else set())
            action = decide(kind)
            print(f"{path}: server copy is {kind} -> {action}")
            if action == "refuse":
                failed += 1
            if action != "replace" or not apply:
                continue
            sftp.rename(ROOT + path, f"{ROOT}{path}.bak.sync.{stamp}")
            temporary = f"{ROOT}{path}.new.{stamp}"
            with sftp.open(temporary, "wb") as handle:
                handle.write(repo)
            sftp.rename(temporary, ROOT + path)
            with sftp.open(ROOT + path, "rb") as handle:
                written = handle.read()
            ok = hashlib.sha256(written).hexdigest() == hashlib.sha256(repo).hexdigest()
            print(f"{path}: replaced, hash {'matches' if ok else 'DOES NOT MATCH'}; backup {path}.bak.sync.{stamp}")
            failed += 0 if ok else 1
    finally:
        sftp.close()
        ssh.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
