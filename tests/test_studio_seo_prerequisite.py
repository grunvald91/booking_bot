import pytest

from scripts.deploy_studio_seo_prerequisite import plan


OLD = b"def article():\n    return 'old'\n"
NEW = b"def article():\n    return 'new'\n"


def test_known_seo_release_and_idempotency():
    assert plan(OLD, OLD, NEW, NEW) == "update"
    assert plan(NEW, OLD, NEW, NEW) == "already"
    assert plan(b"# live comment\n" + OLD, OLD, NEW, NEW) == "update"
    assert plan(b"# live comment\n" + NEW, OLD, NEW, NEW) == "update"


def test_unknown_drift_and_future_unreviewed_release_refused():
    with pytest.raises(ValueError, match="Unrecognized"):
        plan(b"def article():\n    return 'unknown'\n", OLD, NEW, NEW)
    with pytest.raises(ValueError, match="not the reviewed"):
        plan(OLD, OLD, NEW, b"def article():\n    return 'future'\n")
    with pytest.raises(ValueError, match="Unrecognized"):
        plan(b"invalid @@", OLD, NEW, NEW)
