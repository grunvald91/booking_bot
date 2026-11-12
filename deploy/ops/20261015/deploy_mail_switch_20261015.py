"""Mail automation switch + campaign worker service (mail.servgo.ru). Never prints secrets.
Sending stays OFF after deploy: the worker only prepares drafts and heartbeats
until the owner flips the switch in the campaigns dashboard.
Usage on server: python3 deploy_mail_switch_20261015.py deploy|rollback
"""
from pathlib import Path
import sys, json, shutil, subprocess, time, urllib.request, urllib.error

REL = Path('/opt/servgo-releases/20261015/mail-switch'); NEW = REL / 'files'; BACK = REL / 'backup'
ROOT = Path('/opt/booking_bot'); PY = ROOT / 'venv/bin/python'
FILES = ['web/api/routes/mail_campaign_store.py', 'web/api/routes/mail_campaign_worker.py',
         'web/api/routes/mail_campaign_api.py', 'web/api/routes/mail_campaign_dashboard.html']
UNIT = Path('/etc/systemd/system/servgo-mail-worker.service')
UNIT_TEXT = """[Unit]
Description=ServGo Mail campaign worker (sends only while the owner switch is on)
After=network.target postfix.service booking-web-api.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/booking_bot
EnvironmentFile=/opt/booking_bot/.env
EnvironmentFile=/etc/servgo/mail.env
ExecStart=/opt/booking_bot/venv/bin/python -m web.api.routes.mail_campaign_worker
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
"""


def run(*a, **kw): return subprocess.run(list(a), check=True, **kw)


def status(url):
    try:
        with urllib.request.urlopen(url, timeout=8) as r: return r.status
    except urllib.error.HTTPError as e: return e.code
    except Exception: return 0


def wait(url, want, tries=40):
    got = 0
    for _ in range(tries):
        got = status(url)
        if got == want: return
        time.sleep(1)
    raise RuntimeError(f'health {url} -> {got}, want {want}')


def mail_python(code):
    # Same environment files as the services; values never leave the child process.
    return subprocess.check_output(
        ['systemd-run', '--quiet', '--wait', '--pipe', '--collect',
         '-p', 'EnvironmentFile=/opt/booking_bot/.env', '-p', 'EnvironmentFile=/etc/servgo/mail.env',
         '-p', f'WorkingDirectory={ROOT}', str(PY), '-c', code], text=True).strip()


AUTO = ('from web.api.routes.owner_mail import db_open\n'
        'from web.api.routes.mail_campaign_store import initialize, automation_status\n'
        'import json\nwith db_open() as db:\n initialize(db); print(json.dumps(automation_status(db)))')


def deploy():
    if (REL / 'state.json').exists(): raise RuntimeError('already deployed; rollback first')
    BACK.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        q = BACK / f; q.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(ROOT / f, q)
    (REL / 'state.json').write_text(json.dumps({'files': FILES, 'unit_existed': UNIT.exists()}))
    try:
        for f in FILES: shutil.copy2(NEW / f, ROOT / f)
        run(str(PY), '-m', 'py_compile', *[str(ROOT / f) for f in FILES if f.endswith('.py')])
        run('systemctl', 'restart', 'booking-web-api')
        wait('http://127.0.0.1:8000/api/health', 200)
        wait('https://servgo.ru/api/health', 200)
        wait('https://mail.servgo.ru/api/campaigns/automation', 401)
        before = json.loads(mail_python(AUTO))
        if before['enabled']: raise RuntimeError('switch unexpectedly ON before worker start')
        UNIT.write_text(UNIT_TEXT)
        run('systemctl', 'daemon-reload'); run('systemctl', 'enable', '--now', 'servgo-mail-worker')
        time.sleep(20)
        if subprocess.run(['systemctl', 'is-active', '--quiet', 'servgo-mail-worker']).returncode:
            raise RuntimeError('worker not active')
        after = json.loads(mail_python(AUTO))
        if not after['worker_alive'] or after['enabled']: raise RuntimeError(f'worker state {after}')
    except Exception:
        print('MAIL_SWITCH_FAILED_ROLLING_BACK', flush=True); rollback(); raise
    print('MAIL_SWITCH_OK', json.dumps(after))


def rollback():
    st = json.loads((REL / 'state.json').read_text())
    subprocess.run(['systemctl', 'disable', '--now', 'servgo-mail-worker'], capture_output=True)
    if not st['unit_existed'] and UNIT.exists(): UNIT.unlink()
    run('systemctl', 'daemon-reload')
    for f in st['files']: shutil.copy2(BACK / f, ROOT / f)
    run('systemctl', 'restart', 'booking-web-api')
    wait('http://127.0.0.1:8000/api/health', 200)
    (REL / 'state.json').rename(REL / f'state.rolledback.{int(time.time())}.json')
    print('MAIL_SWITCH_ROLLBACK_OK')


if __name__ == '__main__':
    {'deploy': deploy, 'rollback': rollback}[sys.argv[1]]()
