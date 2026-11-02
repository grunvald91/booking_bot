"""Deploy only PR120's three list functions, preserving all other live routes."""
import ast
import os
from pathlib import Path
import subprocess
import time

import paramiko
from scripts.deploy_studio_backend import HOST, ROOT, SERVICE, PinnedKey, read, put, run, wait_health, code_of

BASE = '60c667fc7799d1b728eb97e427d9366301963b24'
PATH = 'web/api/routes/studio_sso.py'
NAMES = ('_businesses_for_studio', 'studio_businesses', 'studio_accessible_businesses')


def functions(source):
    return {n.name: n for n in ast.parse(source).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def equivalent(a, b):
    return ast.dump(a, include_attributes=False) == ast.dump(b, include_attributes=False)


def block(source, node):
    start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
    return start, node.end_lineno, ''.join(source.splitlines(keepends=True)[start:node.end_lineno])


def patch(live, before, desired):
    current, old, new = functions(live), functions(before), functions(desired)
    for name in NAMES:
        if name in current and not equivalent(current[name], new[name]):
            if name not in old or not equivalent(current[name], old[name]):
                raise RuntimeError('Unexpected live list function; refusing overwrite: ' + name)
    if 'studio_businesses' not in current:
        raise RuntimeError('Missing studio_businesses anchor')
    lines = live.splitlines(keepends=True)
    replacements = []
    for name in NAMES:
        if name in current:
            start, end, _ = block(live, current[name])
            replacements.append((start, end, block(desired, new[name])[2]))
    for start, end, value in sorted(replacements, reverse=True):
        lines[start:end] = [value]
    result = ''.join(lines)
    for name in NAMES:
        if name not in current:
            result += '\n\n' + block(desired, new[name])[2] + '\n'
    compile(result, PATH, 'exec')
    return result


def verify(client):
    wait_health(client)
    if run(client, 'systemctl is-active ' + SERVICE) != 'active':
        raise RuntimeError('API is not active')
    for suffix in ('businesses?user_id=0', 'access?user_id=0&business_id=0'):
        if code_of(client, '/internal/studio/' + suffix) != '403':
            raise RuntimeError('Internal endpoint must reject requests without a key')
    # Read the running service environment only inside the host. Never print keys or payloads.
    check = """import json, pathlib, subprocess, urllib.request
pid = subprocess.check_output(['systemctl', 'show', '-p', 'MainPID', '--value', 'booking-web-api.service'], text=True).strip()
env = dict(row.split(b'=', 1) for row in pathlib.Path('/proc/'+pid+'/environ').read_bytes().split(b'\\0') if b'=' in row)
key = env[b'STUDIO_INTERNAL_KEY'].decode()
request = urllib.request.Request('http://127.0.0.1:8000/internal/studio/businesses?user_id=0', headers={'X-Studio-Key': key})
with urllib.request.urlopen(request, timeout=10) as response:
    assert response.status == 200 and json.load(response) == []
print('authenticated_empty_list=ok')
"""
    import shlex
    if run(client, 'python3 -c ' + shlex.quote(check)) != 'authenticated_empty_list=ok':
        raise RuntimeError('Authenticated endpoint check failed')


def main():
    password = os.environ.get('SERVGO_PASSWORD')
    if not password:
        raise RuntimeError('Missing deployment credential')
    before = subprocess.check_output(['git', 'show', BASE + ':' + PATH], text=True)
    desired = Path(PATH).read_text()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedKey())
    client.connect(HOST, username='root', password=password, allow_agent=False,
                   look_for_keys=False, timeout=20, banner_timeout=25, auth_timeout=20)
    sftp = client.open_sftp()
    target = ROOT + '/' + PATH
    original = None
    installed = False
    try:
        wait_health(client)
        original = read(sftp, target)
        if original is None:
            raise RuntimeError('Live SSO route missing')
        updated = patch(original.decode(), before, desired).encode()
        if updated != original:
            backup = target + '.bak.switch.' + str(int(time.time()))
            run(client, 'cp -p ' + target + ' ' + backup)
            if read(sftp, target) != original:
                raise RuntimeError('Live route changed during preflight')
            put(sftp, target, updated, sftp.stat(target).st_mode & 0o777)
            installed = True
            run(client, 'systemctl restart ' + SERVICE)
        verify(client)
        print('studio_switch_deployed=yes; health=200; keyless=403; authorized_list=ok')
    except Exception:
        if installed:
            if read(sftp, target) != updated:
                raise RuntimeError('Concurrent live edit; rollback needs operator review') from None
            put(sftp, target, original)
            run(client, 'systemctl restart ' + SERVICE)
            wait_health(client)
            print('studio_switch_rolled_back=yes')
        raise RuntimeError('Scoped deployment failed; sensitive error details suppressed') from None
    finally:
        sftp.close()
        client.close()


if __name__ == '__main__':
    main()
