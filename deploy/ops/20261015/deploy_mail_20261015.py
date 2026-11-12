"""Scoped owner-mail release (mail.servgo.ru). Never prints secrets.
Does NOT enable the campaign worker: nothing is sent automatically.
Usage on server: /opt/booking_bot/venv/bin/python deploy_mail_20261015.py deploy|rollback
"""
from pathlib import Path
import os, sys, json, shutil, subprocess, time, hashlib, secrets, asyncio
import urllib.request, urllib.error, ssl

REL = Path('/opt/servgo-releases/20261015/mail'); BACK = REL / 'backup'; STATE = REL / 'state.json'
PAY = Path('/opt/servgo-releases/20261014/payload'); ROOT = Path('/opt/booking_bot')
MANIFEST = json.loads((PAY / 'booking-manifest.json').read_text())
FILES = [f for f in MANIFEST['files'] if f.startswith('web/')]  # api + routes + frontend dist (mail branch)
ENVFILE = Path('/etc/servgo/mail.env'); DROPIN = Path('/etc/systemd/system/booking-web-api.service.d/mail.conf')
NGINX = Path('/etc/nginx/sites-available/mail-servgo')


def run(*a, **kw): return subprocess.run(list(a), check=True, **kw)


def status(url, host=None):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={'Host': host} if host else {})
    try:
        with urllib.request.urlopen(req, timeout=6, context=ctx) as r: return r.status
    except urllib.error.HTTPError as e: return e.code
    except Exception: return 0


def wait(url, wanted, tries=30):
    for _ in range(tries):
        got = status(url)
        if got == wanted: return
        time.sleep(1)
    raise RuntimeError(f'health {url} -> {got}, want {wanted}')


def save(path, state):
    p = Path(path)
    if p.exists():
        q = BACK / str(p).lstrip('/'); q.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, q)
        state['backed_up'].append(str(p))
    else:
        state['created'].append(str(p))
    STATE.write_text(json.dumps(state, indent=1))


def owner_values():
    from dotenv import dotenv_values
    env = dict(dotenv_values(ROOT / '.env'))
    os.environ.update({k: v for k, v in env.items() if v is not None})
    # DATABASE_URL lives in the booking-web-api unit (Environment=), not in .env:
    # reuse exactly what the running API uses.
    pid = subprocess.check_output(['systemctl', 'show', '-p', 'MainPID', '--value', 'booking-web-api'], text=True).strip()
    live = dict(x.split('=', 1) for x in Path(f'/proc/{pid}/environ').read_text().split('\0') if '=' in x)
    if not live.get('DATABASE_URL'): raise RuntimeError('DATABASE_URL not found in running booking-web-api')
    os.environ['DATABASE_URL'] = live['DATABASE_URL']
    sys.path.insert(0, str(ROOT))
    from bot.config import ADMIN_IDS
    from web.api.database import async_session, User
    from sqlalchemy import select
    grow = json.loads(subprocess.check_output(['docker', 'inspect', 'ai-growth-os-telegram-1'], text=True))[0]
    gid = dict(x.split('=', 1) for x in grow['Config']['Env'] if '=' in x).get('TELEGRAM_OWNER_CHAT_ID')
    ids = [int(gid)] if gid and int(gid) in ADMIN_IDS else list(ADMIN_IDS)
    if len(ids) != 1: raise RuntimeError('platform owner is ambiguous')

    async def find():
        async with async_session() as db:
            rows = (await db.execute(select(User.id).where(User.telegram_id == ids[0]))).scalars().all()
            if len(rows) != 1: raise RuntimeError('owner user not found uniquely')
            return rows[0]
    sender = env.get('SERVGO_MAIL_FROM') or env.get('SMTP_FROM_EMAIL') or env.get('SMTP_FROM')
    if not sender or '@' not in sender: raise RuntimeError('sender not configured')
    prev = dotenv_values(ENVFILE) if ENVFILE.exists() else {}
    v = {'SERVGO_MAIL_OWNER_USER_ID': asyncio.run(find()),
         'SERVGO_MAIL_SESSION_SECRET': prev.get('SERVGO_MAIL_SESSION_SECRET') or secrets.token_urlsafe(48),
         'SERVGO_MAIL_DATA_DIR': '/var/lib/servgo-owner-mail', 'SERVGO_MAIL_FROM': sender,
         'SERVGO_MAIL_AI_MODEL': env.get('CLAUDEHUB_MODEL', 'grok-4.7'), 'SERVGO_MAIL_DAILY_LIMIT': 50}
    for k in ['SERVGO_MAIL_IMAP_USER', 'SERVGO_MAIL_IMAP_PASSWORD', 'SERVGO_MAIL_IMAP_HOST']:
        if prev.get(k) or env.get(k): v[k] = prev.get(k) or env.get(k)
    return v


NGINX_CONF = '''server {
    listen 80;
    listen [::]:80;
    server_name mail.servgo.ru;
    location ^~ /.well-known/acme-challenge/ { root /var/www/letsencrypt; default_type text/plain; }
    location / { return 301 https://mail.servgo.ru$request_uri; }
}
# ServGo owner mail console, release 20261015.
server {
    listen 443 ssl;
    server_name mail.servgo.ru;
    ssl_certificate /etc/letsencrypt/live/mail.servgo.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mail.servgo.ru/privkey.pem;
    client_max_body_size 5M;
    add_header Cache-Control "no-store" always;
    add_header Referrer-Policy "no-referrer" always;
    location = / { proxy_pass http://127.0.0.1:8000/owner-mail/app; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; }
    location = /claim { access_log off; proxy_pass http://127.0.0.1:8000/owner-mail/claim$is_args$args; proxy_set_header Host $host; }
    location = /unsubscribe { access_log off; proxy_pass http://127.0.0.1:8000/owner-mail/unsubscribe$is_args$args; proxy_set_header Host $host; }
    location /api/ { proxy_pass http://127.0.0.1:8000/owner-mail/api/; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; }
    location / { return 404; }
}
'''


def deploy():
    if STATE.exists(): raise RuntimeError('state exists: previous mail run must be rolled back or inspected first')
    BACK.mkdir(parents=True, exist_ok=True)
    state = {'backed_up': [], 'created': [], 'step': 'start'}
    for n in FILES:  # production must still equal the audited snapshot
        p = ROOT / n; cur = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        if cur != MANIFEST['expected'][n]: raise RuntimeError('production changed since audit: ' + n)
    run('openssl', 'x509', '-noout', '-checkhost', 'mail.servgo.ru', '-checkend', '86400',
        '-in', '/etc/letsencrypt/live/mail.servgo.ru/fullchain.pem', stdout=subprocess.DEVNULL)
    values = owner_values()
    try:
        save(ENVFILE, state); ENVFILE.parent.mkdir(mode=0o700, exist_ok=True)
        ENVFILE.write_text(''.join(f'{k}={json.dumps(str(v))}\n' for k, v in values.items())); ENVFILE.chmod(0o600)
        Path(values['SERVGO_MAIL_DATA_DIR']).mkdir(mode=0o700, exist_ok=True)
        save(DROPIN, state); DROPIN.write_text('[Service]\nEnvironmentFile=/etc/servgo/mail.env\n')
        for n in FILES:
            d = ROOT / n; save(d, state); d.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(PAY / 'booking' / n, d)
        state['step'] = 'files'; STATE.write_text(json.dumps(state, indent=1))
        run('systemctl', 'daemon-reload'); run('systemctl', 'restart', 'booking-web-api')
        wait('http://127.0.0.1:8000/health', 200)
        wait('http://127.0.0.1:8000/owner-mail/permission', 401)
        save(NGINX, state); NGINX.write_text(NGINX_CONF)
        run('nginx', '-t', stderr=subprocess.DEVNULL); run('systemctl', 'reload', 'nginx')
        state['step'] = 'done'; STATE.write_text(json.dumps(state, indent=1))
        wait('https://servgo.ru/api/health', 200); wait('https://mail.servgo.ru/', 401)
        wait('https://servgo.ru/api/owner-mail/permission', 401)
    except Exception:
        print('MAIL_RELEASE_FAILED_ROLLING_BACK', flush=True); rollback(); raise
    print('MAIL_RELEASE_OK', json.dumps({'files': len(FILES), 'imap_configured': bool(values.get('SERVGO_MAIL_IMAP_PASSWORD')), 'worker_enabled': False}))


def rollback():
    state = json.loads(STATE.read_text())
    for p in state['backed_up']:
        shutil.copy2(BACK / p.lstrip('/'), p)
    for p in state['created']:
        Path(p).unlink(missing_ok=True)
    run('systemctl', 'daemon-reload'); run('systemctl', 'restart', 'booking-web-api')
    wait('http://127.0.0.1:8000/health', 200)
    run('nginx', '-t', stderr=subprocess.DEVNULL); run('systemctl', 'reload', 'nginx')
    STATE.rename(STATE.with_suffix('.rolled-back.' + time.strftime('%Y%m%dT%H%M%S')))
    print('MAIL_ROLLBACK_OK', json.dumps({'restored': len(state['backed_up']), 'removed': len(state['created'])}))


if __name__ == '__main__':
    {'deploy': deploy, 'rollback': rollback}[sys.argv[1]]()
