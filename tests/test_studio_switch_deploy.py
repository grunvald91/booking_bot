import subprocess
from pathlib import Path
import pytest
from scripts.deploy_studio_switch import BASE, PATH, patch


def test_scoped_patch_preserves_unrelated_live_changes_and_is_idempotent():
    before = subprocess.check_output(['git', 'show', BASE + ':' + PATH], text=True)
    desired = Path(PATH).read_text()
    live = before + '\n\ndef unrelated_live_route():\n    return "preserve"\n'
    updated = patch(live, before, desired)
    assert 'def unrelated_live_route()' in updated
    assert 'return "preserve"' in updated
    assert '/internal/studio/businesses' in updated
    assert patch(updated, before, desired) == updated


def test_scoped_patch_rejects_changed_permission_logic():
    before = subprocess.check_output(['git', 'show', BASE + ':' + PATH], text=True)
    desired = Path(PATH).read_text()
    live = before.replace('Business.owner_id == user.id', 'Business.owner_id != user.id')
    with pytest.raises(RuntimeError, match='Unexpected live list function'):
        patch(live, before, desired)
