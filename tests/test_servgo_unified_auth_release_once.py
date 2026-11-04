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


def test_sso_patch_preserves_old_source_and_only_intended_hunks():
    from pathlib import Path
    from scripts.release_servgo_unified_auth_once import (
        old_file, patch_live_sso_without_overwriting_server_changes,
    )
    path = "web/api/routes/studio_sso.py"
    old = old_file(path)
    merged = Path(path).read_bytes()
    assert old is not None and old != merged
    revised = patch_live_sso_without_overwriting_server_changes(old, old, merged)
    assert revised is not None
    # Source-level comments may differ; the exact executable AST must agree.
    import ast
    assert ast.dump(ast.parse(revised)) == ast.dump(ast.parse(merged))


def test_sso_patch_rejects_unknown_server_semantic_change():
    from pathlib import Path
    from scripts.release_servgo_unified_auth_once import (
        old_file, patch_live_sso_without_overwriting_server_changes,
    )
    path = "web/api/routes/studio_sso.py"
    old = old_file(path)
    assert old is not None
    merged = Path(path).read_bytes()
    drift = old.replace(b"TICKET_TTL_SECONDS = 60", b"TICKET_TTL_SECONDS = 600")
    assert drift != old
    assert patch_live_sso_without_overwriting_server_changes(drift, old, merged) is None
