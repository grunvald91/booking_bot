"""Compare production source with every branch of the three platform repositories.

Read-only on the server. Public log: only counts, paths and statuses. Server files that are
not identical to main go into an archive encrypted to the auditor's X25519 public key.
"""
import base64, hashlib, io, json, os, pathlib, re, shlex, subprocess, sys, tarfile, time, zipfile
from collections import defaultdict

import paramiko
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PUBLIC_KEY = '3gET2Hgy/Y2VcN/y1O1z3DangYAFUtAvgNJIE0XcYH0='
HOST, HOST_FP = '155.212.162.47', 'uQJp3lT4golKb3lsDTCFozGWR1ihlu1w/Oa4cSzCdpU'
REPOS = {'booking_bot': 'mirrors/booking_bot', 'Ai_growth_os': 'mirrors/Ai_growth_os', 'SMENA': 'mirrors/SMENA'}
COLLECT = pathlib.Path(__file__).with_name('collect.py').read_text()


def git(repo, *args):
    return subprocess.check_output(['git', '-C', REPOS[repo], *args], text=True)


def blob_id(data):
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def index(repo):
    main = {}
    for line in git(repo, 'ls-tree', '-r', 'refs/heads/main').splitlines():
        meta, path = line.split('\t', 1)
        main[path] = meta.split()[2]
    tips = defaultdict(set)  # (path, blob) -> branches
    for ref in git(repo, 'for-each-ref', '--format=%(refname:short)', 'refs/heads').split():
        for line in git(repo, 'ls-tree', '-r', ref).splitlines():
            meta, path = line.split('\t', 1)
            tips[(path, meta.split()[2])].add(ref)
    history = {line.split()[0] for line in git(repo, 'rev-list', '--all', '--objects').splitlines()}
    return main, tips, history


class Pinned(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        actual = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
        if actual != HOST_FP:
            raise paramiko.SSHException('Host key mismatch')
        client.get_host_keys().add(hostname, key.get_name(), key)


def run(ssh, command, stdin=b''):
    chan = ssh.get_transport().open_session()
    chan.exec_command(command)
    if stdin:
        chan.sendall(stdin)
    chan.shutdown_write()
    out, err = io.BytesIO(), io.BytesIO()
    while True:
        while chan.recv_ready():
            out.write(chan.recv(1 << 16))
        while chan.recv_stderr_ready():
            err.write(chan.recv_stderr(1 << 16))
        if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
            break
        time.sleep(0.05)
    return chan.recv_exit_status(), out.getvalue(), err.getvalue()


def collect(ssh, root, include, *, container=None, all_files=False):
    arg = shlex.quote(json.dumps({'root': root, 'include': include, 'all_files': all_files}))
    command = f'python3 - {arg}'
    if container:
        command = f'docker exec -i {container} python3 - {arg}'
    code, data, err = run(ssh, command, COLLECT.encode())
    files = {}
    if code != 0 or not data:
        print(f'  collect {container or ""}:{root} failed: exit {code}')
        return files
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
        for member in tar:
            if member.isfile():
                files[member.name] = tar.extractfile(member).read()
    return files


def main():
    indexes = {repo: index(repo) for repo in REPOS}
    ssh = None
    for attempt in range(3):
        conn = paramiko.SSHClient(); conn.set_missing_host_key_policy(Pinned())
        try:
            conn.connect(HOST, username='root', password=os.environ['SERVER_PASSWORD'], look_for_keys=False,
                         allow_agent=False, timeout=15, banner_timeout=30, auth_timeout=20)
            ssh = conn; break
        except (paramiko.SSHException, OSError, EOFError):
            conn.close()
            if attempt == 2:
                raise
            time.sleep(20)

    _, opt, _ = run(ssh, 'ls -1 /opt')
    print('/opt:', ' '.join(opt.decode().split()))
    _, ps, _ = run(ssh, "docker ps --format '{{.Names}} {{.Image}}'")
    print('containers:', '; '.join(ps.decode().splitlines()))
    _, units, _ = run(ssh, "systemctl list-units --type=service --state=running --no-legend --plain | awk '{print $1}' "
                           "| grep -E -i 'booking|servgo|growth|smena|mail|dovecot|postfix|nginx' | tr '\\n' ' '")
    print('services:', units.decode())
    _, nginx_dump, _ = run(ssh, 'nginx -T 2>/dev/null')
    roots = defaultdict(set)
    for block in re.split(r'\n\s*server\s*\{', nginx_dump.decode(errors='replace')):
        names = re.findall(r'server_name\s+([^;]+);', block)
        for root in re.findall(r'^\s*root\s+([^;]+);', block, re.M):
            for name in ' '.join(names).split():
                roots[name].add(root.strip())
    print('nginx roots:', json.dumps({k: sorted(v) for k, v in sorted(roots.items())}, ensure_ascii=False))

    components = [
        ('booking_bot', '/opt/booking_bot', collect(ssh, '/opt/booking_bot', [''])),
        ('Ai_growth_os', '/app (api container)', collect(ssh, '/app', ['app', 'products', 'alembic', 'deploy', 'pyproject.toml'],
                                                         container='ai-growth-os-api-1')),
        ('ops:/opt/ai_growth_os', '/opt/ai_growth_os', collect(ssh, '/opt/ai_growth_os', [''])),
        ('ops:/opt/servgo-releases', '/opt/servgo-releases', collect(ssh, '/opt/servgo-releases', [''])),
        ('ops:nginx', '/etc/nginx', collect(ssh, '/etc/nginx', ['nginx.conf', 'sites-enabled', 'sites-available', 'conf.d'], all_files=True)),
        ('ops:systemd', '/etc/systemd/system', collect(ssh, '/etc/systemd/system', [''], all_files=False)),
    ]
    for name in sorted(roots):
        if 'smena' in name:
            for root in sorted(roots[name]):
                components.append((f'SMENA:{name}', root, collect(ssh, root, [''])))
    ssh.close()

    manifest, archive = {}, {}
    for label, root, files in components:
        repo = label if label in REPOS else ('SMENA' if label.startswith('SMENA') else None)
        stats = defaultdict(list)
        for path, data in sorted(files.items()):
            if label == 'ops:systemd' and not re.search(r'booking|servgo|growth|smena|mail', path, re.I):
                continue
            blob = blob_id(data)
            status, where = 'unknown', ''
            if repo:
                main_map, tips, history = indexes[repo]
                if main_map.get(path) == blob:
                    status = 'main'
                elif (path, blob) in tips:
                    status, where = 'branch', ','.join(sorted(tips[(path, blob)])[:3])
                elif blob in history:
                    status = 'history'
                elif path in main_map:
                    status = 'changed'
            else:
                hits = [r for r, (_, _, history) in indexes.items() if blob in history]
                status, where = ('in_repo', ','.join(hits)) if hits else ('unknown', '')
            stats[status].append((path, where))
            if status not in ('main', 'in_repo'):
                archive[f'{label}/{path}'] = data
        missing = []
        if repo == 'booking_bot':
            main_map = indexes[repo][0]
            src = ('bot/', 'database/', 'web/api/', 'webapp/', 'migrations/', 'scripts/')
            missing = sorted(p for p in main_map if p.startswith(src) and p.endswith('.py') and p not in files)
        manifest[label] = {'root': root, 'files': len(files), **{k: [p for p, _ in v] for k, v in stats.items()},
                           'missing_on_server_py': missing}
        print(f'\n## {label} ({root}): files={len(files)} ' +
              ' '.join(f'{k}={len(v)}' for k, v in sorted(stats.items())) + f' missing_main_py={len(missing)}')
        for status in ('changed', 'unknown', 'branch', 'history'):
            for path, where in stats.get(status, [])[:400]:
                print(f'  {status:8} {path}' + (f'  [{where}]' if where else ''))
        for path in missing[:200]:
            print(f'  missing  {path}')

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path, data in archive.items():
            zf.writestr(path, data)
        zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=1))
    public = x25519.X25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY))
    ephemeral = x25519.X25519PrivateKey.generate()
    salt, nonce = os.urandom(32), os.urandom(12)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b'servgo-server-sync-v1').derive(ephemeral.exchange(public))
    header = {'ephemeral': base64.b64encode(ephemeral.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode(),
        'salt': base64.b64encode(salt).decode(), 'nonce': base64.b64encode(nonce).decode()}
    pathlib.Path('server-sync.enc').write_bytes(json.dumps(header).encode() + b'\n' +
                                                AESGCM(key).encrypt(nonce, buffer.getvalue(), None))
    print(f'\nencrypted archive: {len(archive)} files, {pathlib.Path("server-sync.enc").stat().st_size} bytes')


if __name__ == '__main__':
    main()
