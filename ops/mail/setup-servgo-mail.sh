#!/usr/bin/env bash
set -Eeuo pipefail

DOMAIN="servgo.ru"
MAIL_HOST="mail.servgo.ru"
SERVER_IP="155.212.162.47"
ROOT="/opt/booking_bot"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/root/servgo-mail-backup-$STAMP"

mkdir -p "$BACKUP"

export DEBIAN_FRONTEND=noninteractive

# The VPS may be running apt-daily/unattended-upgrades. Wait safely rather than
# competing for dpkg/debconf locks.
for lock in /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/debconf/config.dat; do
  for _ in $(seq 1 60); do
    if ! fuser "$lock" >/dev/null 2>&1; then break; fi
    sleep 2
  done
done
dpkg --configure -a || true

echo "postfix postfix/mailname string $DOMAIN" | debconf-set-selections
echo "postfix postfix/main_mailer_type select Internet Site" | debconf-set-selections
apt-get update -qq
apt-get install -y postfix dovecot-core dovecot-imapd dovecot-lmtpd opendkim opendkim-tools fail2ban

for p in /etc/postfix /etc/dovecot /etc/opendkim.conf /etc/opendkim /etc/fail2ban; do
  [ -e "$p" ] && cp -a "$p" "$BACKUP/" || true
done

# ACME vhost for the mail hostname. It does not serve a webmail UI.
mkdir -p /var/www/letsencrypt/.well-known/acme-challenge
cat >/etc/nginx/sites-available/mail-servgo <<'NGINX'
server {
    listen 80;
    listen [::]:80;
    server_name mail.servgo.ru;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
        default_type text/plain;
    }

    location / {
        return 302 https://servgo.ru;
    }
}
NGINX
ln -sfn /etc/nginx/sites-available/mail-servgo /etc/nginx/sites-enabled/mail-servgo
nginx -t
systemctl reload nginx

if [ ! -s /etc/letsencrypt/live/mail.servgo.ru/fullchain.pem ]; then
  certbot certonly --webroot -w /var/www/letsencrypt \
    -d mail.servgo.ru \
    --non-interactive --agree-tos --email admin@servgo.ru
fi

# Dedicated virtual-mail user.
if ! getent group vmail >/dev/null; then groupadd -g 5000 vmail; fi
if ! id vmail >/dev/null 2>&1; then
  useradd -u 5000 -g vmail -d /var/mail/vhosts -s /usr/sbin/nologin vmail
fi
mkdir -p /var/mail/vhosts/servgo.ru/support/Maildir/{cur,new,tmp}
chown -R vmail:vmail /var/mail/vhosts
chmod -R 0700 /var/mail/vhosts/servgo.ru/support

# Generate mailbox password once; never print it to logs.
CRED_FILE=/root/servgo-mail-credentials.txt
if [ ! -s "$CRED_FILE" ]; then
  MAIL_PASS="$(openssl rand -base64 30 | tr -d '\n')"
  printf 'IMAP/SMTP login: support@servgo.ru\nPassword: %s\nIMAP: mail.servgo.ru:993 SSL/TLS\nSMTP: mail.servgo.ru:587 STARTTLS\n' "$MAIL_PASS" >"$CRED_FILE"
  chmod 600 "$CRED_FILE"
else
  MAIL_PASS="$(awk -F': ' '/^Password:/{print $2}' "$CRED_FILE")"
fi
MAIL_HASH="$(doveadm pw -s BLF-CRYPT -p "$MAIL_PASS")"
printf 'support@servgo.ru:%s\n' "$MAIL_HASH" >/etc/dovecot/users
chown root:dovecot /etc/dovecot/users
chmod 0640 /etc/dovecot/users

cat >/etc/dovecot/conf.d/10-auth.conf <<'DOVAUTH'
disable_plaintext_auth = yes
auth_mechanisms = plain login
passdb {
  driver = passwd-file
  args = scheme=BLF-CRYPT username_format=%u /etc/dovecot/users
}
userdb {
  driver = static
  args = uid=vmail gid=vmail home=/var/mail/vhosts/%d/%n
}
DOVAUTH

cat >/etc/dovecot/conf.d/99-servgo.conf <<'DOV'
protocols = imap lmtp
mail_location = maildir:/var/mail/vhosts/%d/%n/Maildir
first_valid_uid = 5000
last_valid_uid = 5000
ssl = required
ssl_min_protocol = TLSv1.2
ssl_cert = </etc/letsencrypt/live/mail.servgo.ru/fullchain.pem
ssl_key = </etc/letsencrypt/live/mail.servgo.ru/privkey.pem

service imap-login {
  inet_listener imap {
    port = 0
  }
  inet_listener imaps {
    port = 993
    ssl = yes
  }
}

service lmtp {
  unix_listener /var/spool/postfix/private/dovecot-lmtp {
    mode = 0600
    user = postfix
    group = postfix
  }
}

service auth {
  unix_listener /var/spool/postfix/private/auth {
    mode = 0660
    user = postfix
    group = postfix
  }
}
DOV

# Virtual addresses. All service aliases land in the support mailbox.
cat >/etc/postfix/vmailbox <<'VMAIL'
support@servgo.ru servgo.ru/support/
VMAIL
postmap /etc/postfix/vmailbox

cat >/etc/postfix/virtual <<'VALIASES'
admin@servgo.ru support@servgo.ru
info@servgo.ru support@servgo.ru
hello@servgo.ru support@servgo.ru
dmarc@servgo.ru support@servgo.ru
postmaster@servgo.ru support@servgo.ru
abuse@servgo.ru support@servgo.ru
noreply@servgo.ru support@servgo.ru
VALIASES
postmap /etc/postfix/virtual

postconf -e "myhostname = mail.servgo.ru"
postconf -e "mydomain = servgo.ru"
postconf -e 'myorigin = $mydomain'
postconf -e "inet_interfaces = all"
postconf -e "inet_protocols = ipv4"
postconf -e 'mydestination = $myhostname, localhost.$mydomain, localhost'
postconf -e "mynetworks = 127.0.0.0/8"
postconf -e "virtual_mailbox_domains = servgo.ru"
postconf -e "virtual_mailbox_base = /var/mail/vhosts"
postconf -e "virtual_mailbox_maps = hash:/etc/postfix/vmailbox"
postconf -e "virtual_alias_maps = hash:/etc/postfix/virtual"
postconf -e "virtual_uid_maps = static:5000"
postconf -e "virtual_gid_maps = static:5000"
postconf -e "virtual_transport = lmtp:unix:private/dovecot-lmtp"
postconf -e "smtpd_tls_cert_file = /etc/letsencrypt/live/mail.servgo.ru/fullchain.pem"
postconf -e "smtpd_tls_key_file = /etc/letsencrypt/live/mail.servgo.ru/privkey.pem"
postconf -e "smtpd_tls_security_level = may"
postconf -e "smtp_tls_security_level = may"
postconf -e "smtpd_tls_auth_only = yes"
postconf -e "smtpd_sasl_type = dovecot"
postconf -e "smtpd_sasl_path = private/auth"
postconf -e "smtpd_sasl_auth_enable = no"
postconf -e "smtpd_relay_restrictions = permit_mynetworks, permit_sasl_authenticated, reject_unauth_destination"
postconf -e "smtpd_recipient_restrictions = permit_mynetworks, permit_sasl_authenticated, reject_unauth_destination"
postconf -e "disable_vrfy_command = yes"
postconf -e "smtpd_helo_required = yes"
postconf -e "message_size_limit = 26214400"
postconf -e "mailbox_size_limit = 0"
postconf -e "recipient_delimiter = +"
# Keep outgoing HELO aligned with the current PTR until provider changes PTR.
postconf -e "smtp_helo_name = artur.grunvald1991.fvds.ru"

# Enable authenticated submission on 587.
python3 - <<'PY'
from pathlib import Path
p=Path('/etc/postfix/master.cf')
s=p.read_text()
marker='# SERVGO SUBMISSION\n'
if marker in s:
    s=s.split(marker)[0].rstrip()+'\n'
s += """\n# SERVGO SUBMISSION
submission inet n       -       y       -       -       smtpd
  -o syslog_name=postfix/submission
  -o smtpd_tls_security_level=encrypt
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_client_restrictions=permit_sasl_authenticated,reject
  -o smtpd_relay_restrictions=permit_sasl_authenticated,reject
  -o smtpd_recipient_restrictions=permit_sasl_authenticated,reject
"""
p.write_text(s)
PY

# DKIM key and signer.
mkdir -p /etc/opendkim/keys/servgo.ru
if [ ! -s /etc/opendkim/keys/servgo.ru/servgo.private ]; then
  opendkim-genkey -b 2048 -D /etc/opendkim/keys/servgo.ru -d servgo.ru -s servgo
fi
chown -R opendkim:opendkim /etc/opendkim/keys
chmod 0700 /etc/opendkim/keys/servgo.ru
chmod 0600 /etc/opendkim/keys/servgo.ru/servgo.private

cat >/etc/opendkim.conf <<'ODK'
Syslog                  yes
SyslogSuccess           yes
LogWhy                   yes
UMask                    007
Mode                     sv
Canonicalization         relaxed/simple
SubDomains               no
OversignHeaders          From
UserID                   opendkim
PidFile                  /run/opendkim/opendkim.pid
Socket                   inet:8891@127.0.0.1
KeyTable                 refile:/etc/opendkim/key.table
SigningTable             refile:/etc/opendkim/signing.table
ExternalIgnoreList       refile:/etc/opendkim/trusted.hosts
InternalHosts            refile:/etc/opendkim/trusted.hosts
ODK
cat >/etc/opendkim/key.table <<'KT'
servgo._domainkey.servgo.ru servgo.ru:servgo:/etc/opendkim/keys/servgo.ru/servgo.private
KT
cat >/etc/opendkim/signing.table <<'ST'
*@servgo.ru servgo._domainkey.servgo.ru
ST
cat >/etc/opendkim/trusted.hosts <<'TH'
127.0.0.1
localhost
155.212.162.47
mail.servgo.ru
TH

postconf -e "milter_default_action = accept"
postconf -e "milter_protocol = 6"
postconf -e "smtpd_milters = inet:127.0.0.1:8891"
postconf -e "non_smtpd_milters = inet:127.0.0.1:8891"

# Basic brute-force protection.
cat >/etc/fail2ban/jail.d/servgo-mail.local <<'F2B'
[postfix-sasl]
enabled = true
port = smtp,submission
backend = systemd

[dovecot]
enabled = true
port = imaps,submission
backend = systemd
F2B

# Open firewall ports only when UFW is already active.
if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
  ufw allow 25/tcp
  ufw allow 587/tcp
  ufw allow 993/tcp
fi

# App-side defaults: local relay, no SMTP password required.
python3 - <<'PY'
from pathlib import Path
p=Path('/opt/booking_bot/.env')
lines=p.read_text().splitlines() if p.exists() else []
values={
    'SMTP_HOST':'127.0.0.1',
    'SMTP_PORT':'25',
    'SMTP_FROM_EMAIL':'noreply@servgo.ru',
    'SMTP_FROM_NAME':'ServGo',
    'SMTP_USE_TLS':'false',
    'MAIL_DOMAIN':'servgo.ru',
}
seen=set()
out=[]
for line in lines:
    if '=' in line and not line.lstrip().startswith('#'):
        k=line.split('=',1)[0].strip()
        if k in values:
            out.append(f'{k}={values[k]}')
            seen.add(k)
            continue
    out.append(line)
for k,v in values.items():
    if k not in seen:
        out.append(f'{k}={v}')
p.write_text('\n'.join(out).rstrip()+'\n')
PY
chmod 600 "$ROOT/.env"

cat >/etc/letsencrypt/renewal-hooks/deploy/servgo-mail-reload.sh <<'HOOK'
#!/usr/bin/env bash
systemctl reload postfix || true
systemctl reload dovecot || true
HOOK
chmod 0755 /etc/letsencrypt/renewal-hooks/deploy/servgo-mail-reload.sh

postfix check
dovecot -n >/tmp/dovecot-servgo.txt
systemctl enable opendkim dovecot postfix fail2ban
systemctl restart opendkim dovecot fail2ban
postfix stop || true
sleep 1
postfix start

# Local delivery smoke test.
printf 'Subject: ServGo mail local smoke test\nFrom: noreply@servgo.ru\nTo: support@servgo.ru\n\nMail server is alive.\n' \
  | /usr/sbin/sendmail -f noreply@servgo.ru support@servgo.ru
sleep 2
LOCAL_MAILS="$(find /var/mail/vhosts/servgo.ru/support/Maildir/new -type f | wc -l)"
test "$LOCAL_MAILS" -ge 1

echo "mail_setup=success"
echo "local_mail_count=$LOCAL_MAILS"
echo "backup_dir=$BACKUP"
echo "smtp_25=$(systemctl is-active postfix)"
echo "imap_993=$(systemctl is-active dovecot)"
echo "dkim=$(systemctl is-active opendkim)"
echo "fail2ban=$(systemctl is-active fail2ban)"
ss -lntp | egrep ':(25|587|993)\b' || true
