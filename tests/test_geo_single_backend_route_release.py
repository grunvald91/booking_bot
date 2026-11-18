"""Offline-only guards for a single-file GEO company blog release."""
from scripts.geo_single_backend_route_release import state


def test_existing_reviewed_file_is_safe_for_scoped_update():
    assert state(b"old", b"old", b"new") == "safe_update"


def test_deployed_file_is_noop():
    assert state(b"new", b"old", b"new") == "already"


def test_divergent_file_or_missing_file_is_refused():
    assert state(b"custom", b"old", b"new") == "conflict"
    assert state(None, b"old", b"new") == "conflict"
