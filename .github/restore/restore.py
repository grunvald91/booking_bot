"""Restore /opt/booking_bot application code to main after the 2026-10-18 17:50 UTC incident.

Old one-off release workflows re-ran when branch history was rewritten and left mixed old code.
The 17:01 UTC audit showed the application code equal to main, so main is the known-good state.

One SSH connection. Only files that differ from main are backed up, replaced and verified.
On a failed health check the backup is restored. The log shows paths and statuses only.
"""
import base64, hashlib, io, json, os, pathlib, subprocess, sys, tarfile, time

import paramiko

HOST, HOST_FP = '155.212.162.47', 'uQJp3lT4golKb3lsDTCFozGWR1ihlu1w/Oa4cSzCdpU'
ROOT = '/opt/booking_bot'
ROOTS = ('bot/', 'database/', 'web/api/', 'webapp/', 'migrations/')
EXTS = ('.py', '.html', '.css', '.js', '.sql', '.json', '.txt', '.yaml', '.yml', '.svg')
BACKUP = '/opt/booking_bot/backups/incident-20261018'
DRY_RUN = os.environ.get('DRY_RUN') == '1'


class Pinned(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        fp = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
        if fp != HOST_FP:
            raise paramiko.SSHException('Host key mismatch')
        client.get_host_keys().add(hostname, key.get_name(), key)


def run(ssh, cmd, stdin=b'', timeout=180):
    chan = ssh.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    if stdin:
        chan.sendall(stdin)
    chan.shutdown_write()
    out, err = io.BytesIO(), io.BytesIO()
    while True:
        while chan.recv_ready():
            out.write(chan.recv(65536))
        while chan.recv_stderr_ready():
            err.write(chan.recv_stderr(65536))
        if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
            break
        time.sleep(0.05)
    return chan.recv_exit_status(), out.getvalue().decode(errors='replace'), err.getvalue().decode(errors='replace')


def main():
    tracked = [p for p in subprocess.check_output(['git', 'ls-files'], text=True).split('\n')
               if p.startswith(ROOTS) and p.endswith(EXTS)]
    local = {p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in tracked}

    ssh = None
    for attempt in range(3):
        c = paramiko.SSHClient(); c.set_missing_host_key_policy(Pinned())
        try:
            c.connect(HOST, username='root', password=os.environ['SERVER_PASSWORD'], look_for_keys=False,
                      allow_agent=False, timeout=15, banner_timeout=30, auth_timeout=20)
            ssh = c; break
        except (paramiko.SSHException, OSError, EOFError):
            c.close()
            if attempt == 2:
                raise
            time.sleep(20)

    listing = json.dumps(tracked)
    code, out, _ = run(ssh, f"cd {ROOT} && python3 -c 'import hashlib,json,sys,os\n"
                            "for p in json.load(sys.stdin):\n"
                            "  print(p, hashlib.sha256(open(p,\"rb\").read()).hexdigest() if os.path.isfile(p) else \"MISSING\")'",
                       listing.encode())
    server = dict(line.split(' ', 1) for line in out.splitlines() if ' ' in line)
    changed = sorted(p for p in tracked if server.get(p) != local[p])
    print(f'checked={len(tracked)} differ_from_main={len(changed)}')
    for p in changed:
        print('  differs', p, '(missing on server)' if server.get(p) == 'MISSING' else '')
    _, dist, _ = run(ssh, f"ls -ld --time-style=+%FT%T {ROOT}/web/frontend/dist {ROOT}/web/frontend/dist* 2>/dev/null | awk '{{print $6, $7}}'")
    print('frontend dist dirs:', dist.replace('\n', '; '))
    _, units, _ = run(ssh, 'for u in booking-web-api booking-bot servgo-mail-worker postfix dovecot nginx; do printf "%s=%s " $u $(systemctl is-active $u); done')
    print('services before:', units)
    if DRY_RUN or not changed:
        ssh.close(); return

    existing = [p for p in changed if server.get(p) != 'MISSING']
    code, _, err = run(ssh, f"mkdir -p {BACKUP} && cd {ROOT} && tar czf {BACKUP}/before-restore.tgz -T - && echo ok",
                       '\n'.join(existing).encode())
    print('backup', 'ok' if code == 0 else f'FAILED {err[-200:]}')
    if code != 0:
        raise SystemExit(1)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for p in changed:
            tar.add(p)
    code, _, err = run(ssh, f"cd {ROOT} && tar xzf - --no-same-owner && echo ok", buf.getvalue())
    print('write', 'ok' if code == 0 else f'FAILED {err[-200:]}')

    # Syntax gate only: imports need the services' environment; the restart health check decides.
    check = "cd {r} && ./venv/bin/python -m py_compile {files} && echo compile_ok".format(
        r=ROOT, files=' '.join(p for p in changed if p.endswith('.py')) or 'database/models.py')
    code, out, err = run(ssh, check)
    print('compile check:', 'ok' if code == 0 else (err.strip().splitlines() or ['failed'])[-1][:200])
    healthy = False
    if code == 0:
        run(ssh, 'systemctl reset-failed booking-web-api booking-bot; systemctl restart booking-web-api; sleep 6; systemctl restart booking-bot')
        time.sleep(25)
        _, out, _ = run(ssh, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health; echo; "
                             "systemctl is-active booking-web-api booking-bot | tr '\\n' ' '")
        print('health:', out.replace('\n', ' '))
        healthy = out.startswith('200') and out.count('active') >= 2 and 'inactive' not in out and 'failed' not in out
    if not healthy:
        print('restore did not become healthy: rolling back to the pre-restore files')
        run(ssh, f"cd {ROOT} && tar xzf {BACKUP}/before-restore.tgz && systemctl reset-failed booking-web-api booking-bot; "
                 "systemctl restart booking-web-api booking-bot")
        _, out, _ = run(ssh, "journalctl -u booking-web-api -u booking-bot --since=-3min --no-pager | grep -E 'Error|Traceback' | tail -5")
        print(out[-1500:])
        raise SystemExit(1)
    _, out, _ = run(ssh, "journalctl -u booking-bot --since=-2min --no-pager | grep -E -i 'start polling|Run polling|error' | tail -5 | sed -E 's/bot[0-9]+:[A-Za-z0-9_-]+/bot<redacted>/g'")
    print('bot log:', out)
    print(f'RESTORE_OK files={len(changed)} backup={BACKUP}/before-restore.tgz')
    ssh.close()


if __name__ == '__main__':
    main()
