"""Read-only inspection of side effects of the 2026-10-18 17:49-17:52 UTC replay of old ops workflows.

Prints only states, counts, hashes and paths. No secrets, no personal data.
"""
import base64, hashlib, io, os, time

import paramiko

HOST, HOST_FP = '155.212.162.47', 'uQJp3lT4golKb3lsDTCFozGWR1ihlu1w/Oa4cSzCdpU'

REMOTE = r'''
set -u
R=/opt/booking_bot
echo "=== frontend dist"
for d in $R/web/frontend/dist $R/.release_backups/*20261018*/files/web/frontend/dist; do
  [ -f "$d/index.html" ] && echo "$(stat -c %y "$d/index.html" | cut -c1-19) $(sha256sum "$d/index.html" | cut -c1-12) $(grep -o 'assets/index-[A-Za-z0-9_-]*\.js' "$d/index.html" | head -1) $d"
done
echo "=== release backups made today"
ls -1d $R/.release_backups/*20261018* $R/.growth-attribution-backup-* /root/servgo-mail-backup-* 2>/dev/null
echo "=== mail"
printf 'postfix=%s dovecot=%s opendkim=%s fail2ban=%s\n' $(systemctl is-active postfix) $(systemctl is-active dovecot) $(systemctl is-active opendkim) $(systemctl is-active fail2ban)
for k in inet_interfaces inet_protocols mynetworks smtpd_relay_restrictions smtpd_recipient_restrictions virtual_mailbox_domains; do echo "postconf $k = $(postconf -h $k)"; done
for b in /root/servgo-mail-backup-*; do [ -f $b/postfix/main.cf ] && echo "backup $(basename $b): inet_interfaces=$(grep -E '^inet_interfaces' $b/postfix/main.cf | cut -d= -f2 | tr -d ' ') users_sha=$(sha256sum $b/dovecot/users 2>/dev/null | cut -c1-12)"; done
echo "current dovecot users_sha=$(sha256sum /etc/dovecot/users | cut -c1-12) mtime=$(stat -c %y /etc/dovecot/users | cut -c1-19)"
PW=/root/support-servgo-mailbox-password.txt
if [ -s $PW ]; then
  H=$(cut -d: -f2- /etc/dovecot/users | head -1)
  doveadm pw -t "$H" -p "$(head -1 $PW | tr -d '\n')" >/dev/null 2>&1 && echo "mailbox password 2026-10-15: MATCHES current" || echo "mailbox password 2026-10-15: DOES NOT match current"
  for b in /root/servgo-mail-backup-*; do [ -f $b/dovecot/users ] || continue
    HB=$(cut -d: -f2- $b/dovecot/users | head -1)
    doveadm pw -t "$HB" -p "$(head -1 $PW | tr -d '\n')" >/dev/null 2>&1 && echo "  matches backup $(basename $b)"; done
fi
ls -la --time-style=+%FT%T /opt/servgo-releases/20261015/mail-password/ 2>/dev/null | awk '{print $6, $7}'
ufw status 2>/dev/null | grep -E '^(Status|25|587|993|465)' | tr '\n' '; '; echo
ss -lnt | awk '{print $4}' | grep -E ':(25|587|993|465)$' | tr '\n' ' '; echo
echo "=== nginx"
nginx -t 2>&1 | tail -1
echo "mail-servgo enabled sha=$(sha256sum /etc/nginx/sites-enabled/mail-servgo | cut -c1-12) lines=$(wc -l < /etc/nginx/sites-enabled/mail-servgo) has443=$(grep -c 'listen 443' /etc/nginx/sites-enabled/mail-servgo)"
echo "webapp enabled sha=$(sha256sum /etc/nginx/sites-enabled/webapp | cut -c1-12) mtime=$(stat -c %y /etc/nginx/sites-available/webapp | cut -c1-19)"
ls -1 /etc/nginx/sites-available/ | grep -E 'pwa-backup-20261018' || true
for u in https://servgo.ru/api/health https://servgo.ru/ https://servgo.ru/blog https://mail.servgo.ru/ https://growth.servgo.ru/health; do echo "$u $(curl -s -o /dev/null -m 10 -w '%{http_code}' $u)"; done
echo "=== .env SMTP keys (non-secret values)"
grep -E '^(SMTP_HOST|SMTP_PORT|SMTP_FROM_EMAIL|SMTP_FROM_NAME|SMTP_USE_TLS|MAIL_DOMAIN)=' $R/.env
stat -c 'env mtime %y' $R/.env | cut -c1-30
echo "=== apt"
fuser /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock 2>&1 | head -2; dpkg --audit 2>&1 | head -3
'''

DB = r'''
import asyncio
from sqlalchemy import text
from database import async_session_maker
async def main():
    async with async_session_maker() as s:
        q = text("""
          WITH demo AS (SELECT id FROM users WHERE telegram_id BETWEEN -880026100048 AND -880026100001)
          SELECT b.id, b.name, b.business_type, b.is_active,
            (SELECT count(*) FROM bookings k WHERE k.business_id=b.id AND k.client_id IN (SELECT id FROM demo)
               AND k.booking_date BETWEEN DATE '2026-10-19' AND DATE '2026-11-18') AS demo_new,
            (SELECT count(*) FROM bookings k WHERE k.business_id=b.id AND k.client_id IN (SELECT id FROM demo)
               AND k.booking_date < DATE '2026-10-19') AS demo_earlier,
            (SELECT count(*) FROM bookings k WHERE k.business_id=b.id AND k.client_id NOT IN (SELECT id FROM demo)) AS real_all,
            (SELECT count(*) FROM bookings k WHERE k.business_id=b.id AND k.client_id NOT IN (SELECT id FROM demo)
               AND k.booking_date >= DATE '2026-10-19') AS real_upcoming
          FROM businesses b ORDER BY b.id""")
        for r in (await s.execute(q)).all():
            print('BUSINESS', r.id, repr(r.name)[:40], r.business_type, 'active' if r.is_active else 'inactive',
                  'demo_new', r.demo_new, 'demo_before_19oct', r.demo_earlier, 'real_total', r.real_all, 'real_upcoming', r.real_upcoming)
asyncio.run(main())
'''


class Pinned(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        fp = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
        if fp != HOST_FP:
            raise paramiko.SSHException('Host key mismatch')
        client.get_host_keys().add(hostname, key.get_name(), key)


def run(ssh, cmd, stdin=b''):
    chan = ssh.get_transport().open_session()
    chan.exec_command(cmd)
    if stdin:
        chan.sendall(stdin)
    chan.shutdown_write()
    out = io.BytesIO()
    while not (chan.exit_status_ready() and not chan.recv_ready()):
        while chan.recv_ready():
            out.write(chan.recv(65536))
        while chan.recv_stderr_ready():
            chan.recv_stderr(65536)
        time.sleep(0.05)
    return out.getvalue().decode(errors='replace')


ssh = paramiko.SSHClient(); ssh.set_missing_host_key_policy(Pinned())
ssh.connect(HOST, username='root', password=os.environ['SERVER_PASSWORD'], look_for_keys=False,
            allow_agent=False, timeout=15, banner_timeout=30, auth_timeout=20)
print(run(ssh, 'bash -s', REMOTE.encode()))
print('=== bookings (demo clients are the seed\'s 48 negative-telegram-id users)')
print(run(ssh, 'cd /opt/booking_bot && set -a && . ./.env 2>/dev/null; set +a; '
               'export $(systemctl show booking-web-api -p Environment --value | tr " " "\\n" | grep ^DATABASE_URL=) ; '
               './venv/bin/python - 2>&1 | tail -60', DB.encode()))
ssh.close()
