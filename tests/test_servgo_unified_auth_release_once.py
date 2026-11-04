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


def test_production_style_relocation_and_unused_constant_are_safely_normalized():
    """The observed production drift is only an unused constant + moved handlers."""
    import ast
    from pathlib import Path
    from scripts.release_servgo_unified_auth_once import (
        old_file, patch_live_sso_without_overwriting_server_changes,
    )
    from scripts.deploy_servgo_frontend_atomic import backend_equivalent
    path = "web/api/routes/studio_sso.py"
    old = old_file(path)
    assert old is not None
    desired = Path(path).read_bytes()
    base = old.decode()
    assert 'STUDIO_URL = "https://growth.servgo.ru"' not in base
    tree = ast.parse(base)
    source_lines = base.splitlines(keepends=True)
    moved = []
    ranges = []
    for name in ("_businesses_for_studio", "studio_accessible_businesses"):
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
        end = node.end_lineno
        moved.append("".join(source_lines[start:end]))
        ranges.append((start, end))
    for start, end in sorted(ranges, reverse=True):
        del source_lines[start:end]
    production = "".join(source_lines) + "\n\n" + "\n\n\n".join(moved) + "\n"
    production = production.replace(
        "MIN_SECRET_LENGTH = 32\n",
        'MIN_SECRET_LENGTH = 32\nSTUDIO_URL = "https://growth.servgo.ru"\n',
        1,
    )
    repaired = patch_live_sso_without_overwriting_server_changes(
        production.encode(), old, desired,
    )
    assert repaired is not None
    assert backend_equivalent(path, repaired, desired)
    assert b'STUDIO_URL = "https://growth.servgo.ru"' not in repaired
