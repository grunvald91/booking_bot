"""Verify audited production frontend source provenance and exact build."""
import hashlib
import json
import pathlib
import shutil
import sys

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def safe_path(root, relative):
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Unsafe reference path")
    return path

mode, manifest_path, source, *destination = sys.argv[1:]
manifest = json.loads(pathlib.Path(manifest_path).read_text())
root = pathlib.Path(source)
if mode == "reference":
    target = pathlib.Path(destination[0])
    for name, wanted in manifest["frontend_source"].items():
        path = safe_path(root, name)
        if digest(path) != wanted:
            raise ValueError("Reference source changed: " + name)
        out = safe_path(target, name)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)
    print("Reference source provenance verified.")
elif mode == "dist":
    actual = {str(p.relative_to(root)): digest(p) for p in root.rglob("*") if p.is_file()}
    deployed = manifest["frontend_dist"]
    extras = set(deployed) - set(actual)
    if any(deployed.get(name) != value for name, value in actual.items()):
        raise ValueError("Reference build differs from production.")
    texts = [p.read_text(errors="replace") for p in root.rglob("*") if p.is_file() and p.suffix in {".html", ".js", ".css"}]
    if any(not name.startswith("assets/") or any(pathlib.Path(name).name in text for text in texts) for name in extras):
        raise ValueError("Unexplained active production assets.")
    print("Active reference build matches production byte for byte; retained historical assets:", len(extras))
elif mode == "public":
    rewrite = manifest["public_html_rewrite"]
    expected = root.read_text()
    if expected.count(rewrite["source"]) != 1:
        raise ValueError("Reviewed HTML rewrite source differs")
    expected = expected.replace(rewrite["source"], rewrite["target"])
    if pathlib.Path(destination[0]).read_text() != expected:
        raise ValueError("Public HTML differs from reviewed nginx transformation")
    print("Public HTML matches release with reviewed nginx transformation.")
else:
    raise ValueError("Unknown verification mode")
