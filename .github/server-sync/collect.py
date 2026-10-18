"""Runs ON the server (or inside a container): writes a tar.gz of source-like files to stdout.

Read-only. Argument: JSON {"root": str, "include": [relative paths], "all_files": bool}.
Secrets-looking files are skipped here; the archive is encrypted by the caller anyway.
"""
import io, json, os, sys, tarfile

cfg = json.loads(sys.argv[1])
root = cfg['root'].rstrip('/')
SKIP_DIRS = {'venv', '.venv', 'env', 'node_modules', 'dist', 'build', '__pycache__', '.git', '.cache',
             'uploads', 'media', 'logs', 'log', '_whiteboard', 'backup', 'backups', 'payload',
             '.pytest_cache', '.mypy_cache', 'site-packages', 'tmp'}
EXT = {'.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.css', '.html', '.md', '.sql', '.yaml', '.yml',
       '.toml', '.json', '.sh', '.conf', '.service', '.txt', '.ini', '.cfg', '.xml', '.j2', '.svg'}
SECRET_HINTS = ('.env', '.pem', '.key', 'id_rsa', 'id_ed25519', '.sqlite', '.db', '.log', 'password',
                'credential', 'secret', 'token', '.bak', '.old', '.orig', '.swp')
MAX_FILE, MAX_TOTAL = 2_000_000, 80_000_000
total = 0
out = tarfile.open(fileobj=sys.stdout.buffer, mode='w|gz')


def wanted(name):
    low = name.lower()
    if low.startswith('.env') or any(h in low for h in SECRET_HINTS):
        return False
    return cfg.get('all_files') or os.path.splitext(low)[1] in EXT or low in ('dockerfile', 'makefile')


def add(path, rel):
    global total
    try:
        st = os.stat(path)
    except OSError:
        return
    if st.st_size > MAX_FILE or total + st.st_size > MAX_TOTAL:
        return
    try:
        with open(path, 'rb') as fh:
            data = fh.read()
    except OSError:
        return
    info = tarfile.TarInfo(rel)
    info.size = len(data)
    info.mtime = int(st.st_mtime)
    out.addfile(info, io.BytesIO(data))
    total += len(data)


for item in cfg['include']:
    start = os.path.join(root, item) if item else root
    if os.path.isfile(start):
        if wanted(os.path.basename(start)):
            add(start, os.path.relpath(start, root))
        continue
    for current, dirs, files in os.walk(start, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith('.'))
        for name in sorted(files):
            full = os.path.join(current, name)
            if wanted(name) and (os.path.isfile(full)):
                add(full, os.path.relpath(full, root))
out.close()
