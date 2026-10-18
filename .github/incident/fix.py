"""Undo the side effects of the 2026-10-18 17:49-17:52 UTC replay (frontend build, mailbox, mail site).

Every replaced item is copied to /opt/booking_bot/backups/incident-20261018/ first.
Postfix main.cf and the firewall already match the pre-incident state and are not touched.
"""
import base64, hashlib, io, os, pathlib, time

import paramiko

HOST, HOST_FP = '155.212.162.47', 'uQJp3lT4golKb3lsDTCFozGWR1ihlu1w/Oa4cSzCdpU'
NGINX_MAIL = pathlib.Path(__file__).with_name('mail-servgo.conf').read_text()

REMOTE = r'''
set -u
R=/opt/booking_bot
B=$R/backups/incident-20261018
MB=/root/servgo-mail-backup-20261018-205108
PRE=$R/.release_backups/client-email-4f6f9a4f-20261018-205058/files/web/frontend/dist
mkdir -p $B
fail() { echo "FIX_FAILED: $1"; exit 1; }

echo "=== 1. frontend build"
[ -f $PRE/index.html ] || fail "pre-incident dist backup missing"
if ! cmp -s $PRE/index.html $R/web/frontend/dist/index.html; then
  rm -rf $B/dist-after-incident && cp -a $R/web/frontend/dist $B/dist-after-incident
  rm -rf $R/web/frontend/dist.restore && cp -a $PRE $R/web/frontend/dist.restore
  rm -rf $R/web/frontend/dist && mv $R/web/frontend/dist.restore $R/web/frontend/dist
  echo "dist restored: $(grep -o 'assets/index-[A-Za-z0-9_-]*\.js' $R/web/frontend/dist/index.html | head -1)"
else echo "dist already pre-incident"; fi

echo "=== 2. dovecot (mailbox password of 2026-10-15)"
[ -f $MB/dovecot/users ] || fail "mail backup missing"
rm -rf $B/dovecot-after-incident && cp -a /etc/dovecot $B/dovecot-after-incident
for f in $(cd $MB/dovecot && find . -type f); do cmp -s $MB/dovecot/$f /etc/dovecot/$f || { cp -a $MB/dovecot/$f /etc/dovecot/$f; echo "restored /etc/dovecot/${f#./}"; }; done
doveconf -n >/dev/null 2>&1 || { cp -a $B/dovecot-after-incident/. /etc/dovecot/; fail "dovecot config invalid, reverted"; }
systemctl restart dovecot
H=$(cut -d: -f2- /etc/dovecot/users | head -1)
doveadm pw -t "$H" -p "$(head -1 /root/support-servgo-mailbox-password.txt | tr -d '\n')" >/dev/null 2>&1 && echo "mailbox password: 2026-10-15 value active" || echo "mailbox password: STILL MISMATCH"
doveadm auth test support@servgo.ru "$(head -1 /root/support-servgo-mailbox-password.txt | tr -d '\n')" 2>&1 | grep -o 'auth succeeded\|auth failed' | head -1

echo "=== 3. postfix maps and opendkim (restore only if changed)"
for f in virtual vmailbox; do
  if ! cmp -s $MB/postfix/$f /etc/postfix/$f; then cp -a /etc/postfix/$f $B/postfix-$f-after-incident; cp -a $MB/postfix/$f /etc/postfix/$f; postmap /etc/postfix/$f; echo "restored /etc/postfix/$f"; else echo "/etc/postfix/$f unchanged"; fi
done
cmp -s $MB/opendkim.conf /etc/opendkim.conf && echo "opendkim.conf unchanged" || { cp -a /etc/opendkim.conf $B/opendkim.conf-after-incident; cp -a $MB/opendkim.conf /etc/opendkim.conf; echo "restored opendkim.conf"; }
diff -rq $MB/opendkim /etc/opendkim >/dev/null 2>&1 && echo "/etc/opendkim unchanged" || { cp -a /etc/opendkim $B/opendkim-after-incident; cp -a $MB/opendkim/. /etc/opendkim/; echo "restored /etc/opendkim"; }
systemctl restart opendkim && postfix check && systemctl reload postfix
printf 'postfix=%s dovecot=%s opendkim=%s\n' $(systemctl is-active postfix) $(systemctl is-active dovecot) $(systemctl is-active opendkim)
'''

NGINX = r'''
set -u
B=/opt/booking_bot/backups/incident-20261018
F=/etc/nginx/sites-available/mail-servgo
cp -a $F $B/nginx-mail-servgo-after-incident
cp /root/mail-servgo.incident.new $F && rm -f /root/mail-servgo.incident.new
if nginx -t 2>/dev/null; then systemctl reload nginx; echo "mail-servgo nginx restored (has443=$(grep -c 'listen 443' $F))"
else cp -a $B/nginx-mail-servgo-after-incident $F; nginx -t && systemctl reload nginx; echo "FIX_FAILED: nginx config rejected, reverted"; exit 1; fi
'''

CHECK = r'''
sleep 3
for u in https://servgo.ru/ https://servgo.ru/api/health https://servgo.ru/blog https://mail.servgo.ru/; do echo "$u $(curl -s -o /dev/null -m 10 -w '%{http_code}' $u)"; done
echo "frontend served: $(curl -s -m 10 https://servgo.ru/ | grep -o 'assets/index-[A-Za-z0-9_-]*\.js' | head -1)"
printf 'booking-web-api=%s booking-bot=%s mail-worker=%s nginx=%s\n' $(systemctl is-active booking-web-api) $(systemctl is-active booking-bot) $(systemctl is-active servgo-mail-worker) $(systemctl is-active nginx)
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
    return chan.recv_exit_status(), out.getvalue().decode(errors='replace')


ssh = paramiko.SSHClient(); ssh.set_missing_host_key_policy(Pinned())
ssh.connect(HOST, username='root', password=os.environ['SERVER_PASSWORD'], look_for_keys=False,
            allow_agent=False, timeout=15, banner_timeout=30, auth_timeout=20)
status = 0
code, out = run(ssh, 'bash -s', REMOTE.encode()); print(out); status = code
if status == 0:
    run(ssh, 'cat > /root/mail-servgo.incident.new', NGINX_MAIL.encode())
    code, out = run(ssh, 'bash -s', NGINX.encode()); print(out); status = code
code, out = run(ssh, 'bash -s', CHECK.encode()); print(out)
ssh.close()
raise SystemExit(status)
