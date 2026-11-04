"""Read-only tests for the one-time scoped Studio auth rollout."""
from scripts.release_servgo_unified_auth_once import allowed_change


def test_only_known_old_content_can_be_replaced():
    path = "web/api/routes/auth.py"
    previous = b"def login():\n    return 1\n"
    desired = b"def login():\n    return 2\n"
    assert allowed_change(path, desired, previous, desired) == "already"
    assert allowed_change(path, previous, previous, desired) == "update"
    assert allowed_change(path, b"# server-side comment\ndef login():\n    return 1\n",
                          previous, desired) == "update"
    assert allowed_change(path, b"def login():\n    return 99\n",
                          previous, desired) == "conflict"


def test_only_reviewed_new_file_can_be_created():
    desired = b"def issue():\n    return 'ok'\n"
    assert allowed_change("web/api/studio_identity.py", None, None, desired) == "create"
    assert allowed_change("web/api/routes/auth.py", None, b"original", desired) == "conflict"
    assert allowed_change("web/api/studio_identity.py", b"unknown", None, desired) == "conflict"
