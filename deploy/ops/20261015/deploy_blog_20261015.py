"""Scoped public blog release (servgo.ru/blog). Never prints secrets.
Usage on server: python3 deploy_blog_20261015.py deploy|rollback
"""
from pathlib import Path
import sys, json, shutil, subprocess, time, hashlib
import urllib.request, urllib.error

REL = Path('/opt/servgo-releases/20261015/blog'); BACK = REL / 'backup'; STATE = REL / 'state.json'
PAY = Path('/opt/servgo-releases/20261014/payload'); ROOT = Path('/opt/booking_bot')
MANIFEST = json.loads((PAY / 'booking-manifest.json').read_text())
FILES = [f for f in MANIFEST['files'] if f.startswith('webapp/')]
DROPIN = Path('/etc/systemd/system/booking-bot.service.d/blog.conf')
NGINX = Path('/etc/nginx/sites-enabled/webapp')  # regular file, loaded before webapp.bak_auth3_
MARK = '# ServGo blog release 20261015: scoped routes only.'
SERVER = 'server_name servgo.ru www.servgo.ru 155.212.162.47;'
ROUTES = f'''
    {MARK}
    location = /blog {{ proxy_pass http://127.0.0.1:8080; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; }}
    location ^~ /blog/ {{ proxy_pass http://127.0.0.1:8080; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; }}
    location ^~ /static/blog/ {{ proxy_pass http://127.0.0.1:8080; }}
    location = /static/css/blog.css {{ proxy_pass http://127.0.0.1:8080; }}
    location = /static/css/landing.css {{ proxy_pass http://127.0.0.1:8080; }}
    location = /static/favicon.svg {{ proxy_pass http://127.0.0.1:8080; }}
    location = /static/og.png {{ proxy_pass http://127.0.0.1:8080; }}
'''


def run(*a, **kw): return subprocess.run(list(a), check=True, **kw)


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=8) as r: return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e: return e.code, ''
    except Exception: return 0, ''


def wait(url, wanted, needle=None, tries=40):
    for _ in range(tries):
        code, body = fetch(url)
        if code == wanted and (needle is None or needle in body): return body
        time.sleep(1)
    raise RuntimeError(f'health {url} -> {code}, want {wanted} containing {needle!r}')


def save(path, state):
    p = Path(path)
    if p.exists():
        q = BACK / str(p).lstrip('/'); q.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, q)
        state['backed_up'].append(str(p))
    else:
        state['created'].append(str(p))
    STATE.write_text(json.dumps(state, indent=1))


def deploy():
    if STATE.exists(): raise RuntimeError('state exists: previous blog run must be rolled back or inspected first')
    for n in FILES:
        p = ROOT / n; cur = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        if cur != MANIFEST['expected'][n]: raise RuntimeError('production changed since audit: ' + n)
    text = NGINX.read_text()
    if MARK in text or text.count(SERVER) != 2: raise RuntimeError('unexpected nginx webapp layout')
    BACK.mkdir(parents=True, exist_ok=True)
    state = {'backed_up': [], 'created': []}
    try:
        for n in FILES:
            d = ROOT / n; save(d, state); d.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(PAY / 'booking' / n, d)
        save(DROPIN, state); DROPIN.write_text('[Service]\nEnvironment=BLOG_PUBLIC_ORIGIN=https://servgo.ru\n')
        run('systemctl', 'daemon-reload'); run('systemctl', 'restart', 'booking-bot')
        local = wait('http://127.0.0.1:8080/blog', 200, '<h1')
        # nginx: first server_name occurrence is the 443 block (checked above: exactly 2 blocks).
        save(NGINX, state); NGINX.write_text(text.replace(SERVER, SERVER + ROUTES, 1))
        run('nginx', '-t', stderr=subprocess.DEVNULL); run('systemctl', 'reload', 'nginx')
        body = wait('https://servgo.ru/blog', 200, 'canonical" href="https://servgo.ru/blog"')
        sys.path.insert(0, str(PAY / 'booking'))
        from webapp.blog_content import BLOG_ARTICLES
        for a in BLOG_ARTICLES:
            wait('https://servgo.ru/blog/' + a['slug'], 200, f'/blog/{a["slug"]}')
        wait('https://servgo.ru/blog/no-such-article-20261015', 404)
        wait('https://servgo.ru/blog/sitemap.xml', 200, 'https://servgo.ru/blog/')
        wait('https://servgo.ru/static/css/blog.css?v=1', 200)
        wait('https://servgo.ru/api/health', 200); wait('https://servgo.ru/', 200)
    except Exception:
        print('BLOG_RELEASE_FAILED_ROLLING_BACK', flush=True); rollback(); raise
    print('BLOG_RELEASE_OK', json.dumps({'files': len(FILES), 'articles': len(BLOG_ARTICLES)}))


def rollback():
    state = json.loads(STATE.read_text())
    for p in state['backed_up']:
        shutil.copy2(BACK / p.lstrip('/'), p)
    for p in state['created']:
        Path(p).unlink(missing_ok=True)
    run('systemctl', 'daemon-reload'); run('systemctl', 'restart', 'booking-bot')
    run('nginx', '-t', stderr=subprocess.DEVNULL); run('systemctl', 'reload', 'nginx')
    STATE.rename(STATE.with_suffix('.rolled-back.' + time.strftime('%Y%m%dT%H%M%S')))
    print('BLOG_ROLLBACK_OK', json.dumps({'restored': len(state['backed_up']), 'removed': len(state['created'])}))


if __name__ == '__main__':
    {'deploy': deploy, 'rollback': rollback}[sys.argv[1]]()
