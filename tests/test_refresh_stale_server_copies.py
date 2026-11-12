import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from refresh_stale_server_copies import FILES, decide  # noqa: E402


def test_only_a_copy_that_is_just_behind_git_is_replaced():
    assert decide("behind") == "replace"
    assert decide("same") == "keep"
    for kind in ("unique", "secret", "new"):
        assert decide(kind) == "refuse"  # a hotfix made on the server is never overwritten


def test_the_list_is_exactly_the_three_files_and_all_exist_in_the_repo():
    assert len(FILES) == 3
    root = Path(__file__).resolve().parents[1]
    assert all((root / path).is_file() for path in FILES)
