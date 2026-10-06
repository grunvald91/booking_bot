#!/usr/bin/env bash
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive

BACKUP_ROOT=/root/servgo-mail-backups
mkdir -p "$BACKUP_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
BACKUP="$BACKUP_ROOT/$TS"
mkdir -p "$BACKUP"

[ -d /etc/postfix ] && cp -a /etc/postfix "$BACKUP/postfix-before" || true
[ -d /etc/opendkim ] && cp -a /etc/opendkim "$BACKUP/opendkim-before" || true
cp -a /opt/booking_bot/.env "$BACKUP/booking.env.before"

apt-get update -qq
apt-get install -y -qq postfix opendkim opendkim-tools bsd-mailx

install -d -m 0750 -o opendkim -g opendkim /etc/opendkim/keys/servgo.ru
if [ ! -f /etc/opendkim/keys/servgo.ru/s202610.private ]; then
  opendkim-genkey -b 2048 -d servgo.ru -D /etc/opendkim/keys/servgo.ru -s s202610
fi
chown opendkim:opendkim /etc/opendkim/keys/servgo.ru/s202610.private
chmod 0600 /etc/opendkim/keys/servgo.ru/s202610.private
chmod 0644 /etc/opendkim/keys/servgo.ru/s202610.txt

cat >/etc/opendkim.conf <<'EOF'
Syslog                  yes
SyslogSuccess           yes
Canonicalization        relaxed/simple
Mode                    s
SubDomains              no
OversignHeaders         From
UserID                  opendkim
UMask                    007
Socket                  inet:8891@127.0.0.1
KeyTable                refile:/etc/opendkim/key.table
SigningTable            refile:/etc/opendkim/signing.table
ExternalIgnoreList      refile:/etc/opendkim/trusted.hosts
InternalHosts           refile:/etc/opendkim/trusted.hosts
EOF

cat >/etc/opendkim/key.table <<'EOF'
s202610._domainkey.servgo.ru servgo.ru:s202610:/etc/opendkim/keys/servgo.ru/s202610.private
EOF

cat >/etc/opendkim/signing.table <<'EOF'
*@servgo.ru s202610._domainkey.servgo.ru
EOF

cat >/etc/opendkim/trusted.hosts <<'EOF'
127.0.0.1
localhost
::1
EOF

postconf -e 'myhostname = mail.servgo.ru'
postconf -e 'mydomain = servgo.ru'
postconf -e 'myorigin = servgo.ru'
postconf -e 'inet_interfaces = loopback-only'
postconf -e 'inet_protocols = ipv4'
postconf -e 'mydestination = localhost'
postconf -e 'mynetworks = 127.0.0.0/8'
postconf -e 'relayhost ='
postconf -e 'smtp_helo_name = artur.grunvald1991.fvds.ru'
postconf -e 'smtp_tls_security_level = may'
postconf -e 'smtp_tls_loglevel = 1'
postconf -e 'smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt'
postconf -e 'smtpd_relay_restrictions = permit_mynetworks,reject_unauth_destination'
postconf -e 'milter_default_action = accept'
postconf -e 'milter_protocol = 6'
postconf -e 'smtpd_milters = inet:127.0.0.1:8891'
postconf -e 'non_smtpd_milters = inet:127.0.0.1:8891'
postconf -e 'disable_vrfy_command = yes'
postconf -e 'smtpd_helo_required = yes'

cat >/etc/postfix/sender_canonical <<'EOF'
/^root(@.*)?$/ no-reply@servgo.ru
/^www-data(@.*)?$/ no-reply@servgo.ru
/^booking(@.*)?$/ no-reply@servgo.ru
EOF
postconf -e 'sender_canonical_maps = regexp:/etc/postfix/sender_canonical'

ENV=/opt/booking_bot/.env
set_env() {
  local key="$1" value="$2"
  if grep -q "^$key=" "$ENV"; then
    sed -i "s|^$key=.*|$key=$value|" "$ENV"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV"
  fi
}
set_env SMTP_HOST 127.0.0.1
set_env SMTP_PORT 25
set_env SMTP_FROM no-reply@servgo.ru
set_env SMTP_FROM_NAME ServGo
set_env SMTP_USE_TLS false

opendkim -n
postfix check
systemctl enable --now opendkim
systemctl enable --now postfix
systemctl restart opendkim
systemctl restart postfix

test "$(systemctl is-active opendkim)" = active
test "$(systemctl is-active postfix)" = active

python3 - <<'PY'
import smtplib
with smtplib.SMTP('127.0.0.1',25,timeout=5) as s:
    code,msg=s.ehlo()
    assert code == 250, (code,msg)
print('local_smtp_ehlo=ok')
PY

echo "backup_dir=$BACKUP"
echo "postfix=$(systemctl is-active postfix)"
echo "opendkim=$(systemctl is-active opendkim)"
echo "dkim_record_begin"
cat /etc/opendkim/keys/servgo.ru/s202610.txt
echo "dkim_record_end"
