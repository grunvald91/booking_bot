"""Apply migrations/add_booking_overlap_constraint.sql on production (approved by owner 2026-10-20).

Backup of the bookings table first; migration in ONE transaction (rolls back fully on any error);
restart web API and bot; verify the column error is gone. Prints statuses only.
"""
import base64, hashlib, os, pathlib, time
import paramiko

HOST, FP = '155.212.162.47', 'uQJp3lT4golKb3lsDTCFozGWR1ihlu1w/Oa4cSzCdpU'
MIGRATION = pathlib.Path('migrations/add_booking_overlap_constraint.sql').read_bytes()

class Pinned(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        if base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=') != FP:
            raise paramiko.SSHException('Host key mismatch')
        client.get_host_keys().add(hostname, key.get_name(), key)

REMOTE = r'''
set -u
B=/opt/booking_bot/backups/db-20261020
mkdir -p $B
PSQL="sudo -u postgres psql -d booking_bot -v ON_ERROR_STOP=1 -At"
cd /tmp
echo "== before"
$PSQL -c "select 'has_column='||count(*) from information_schema.columns where table_name='bookings' and column_name='resource_duration_minutes'"
echo "== backup bookings table"
sudo -u postgres pg_dump -d booking_bot -t bookings | gzip > $B/bookings-before.sql.gz || { echo "BACKUP_FAILED"; exit 1; }
echo "backup_bytes=$(stat -c %s $B/bookings-before.sql.gz)"
echo "== migrate (single transaction)"
chmod 644 /tmp/overlap_migration.sql
if sudo -u postgres psql -d booking_bot -v ON_ERROR_STOP=1 -1 -q -f /tmp/overlap_migration.sql; then echo "MIGRATION_OK"; else echo "MIGRATION_FAILED (rolled back)"; exit 1; fi
echo "== after"
$PSQL -c "select 'columns='||string_agg(column_name,',') from information_schema.columns where table_name='bookings' and column_name in ('resource_duration_minutes','occupies_resource')"
$PSQL -c "select 'null_durations='||count(*) from bookings where resource_duration_minutes is null"
$PSQL -c "select 'constraint='||count(*) from pg_constraint where conname='bookings_no_active_resource_overlap'"
echo "== restart"
T=$(date '+%Y-%m-%d %H:%M:%S')
systemctl restart booking-web-api booking-bot
for i in $(seq 1 20); do c=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://127.0.0.1:8000/health || true); [ "$c" = "200" ] && break; sleep 2; done
echo "api_health=$c web=$(systemctl is-active booking-web-api) bot=$(systemctl is-active booking-bot)"
sleep 25
echo "column_errors_after_restart_api=$(journalctl -u booking-web-api --since "$T" --no-pager -o cat | grep -c 'resource_duration_minutes\|occupies_resource')"
echo "column_errors_after_restart_bot=$(journalctl -u booking-bot --since "$T" --no-pager -o cat | grep -c 'resource_duration_minutes\|occupies_resource')"
echo "attention_unauth=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8000/admin/prepayments/attention)"
'''

def main():
    pw = os.environ['SERVER_PASSWORD']
    for attempt in range(3):
        c = paramiko.SSHClient(); c.set_missing_host_key_policy(Pinned())
        try:
            c.connect(HOST, username='root', password=pw, look_for_keys=False, allow_agent=False, timeout=15, banner_timeout=30, auth_timeout=20)
            break
        except (paramiko.SSHException, OSError, EOFError):
            c.close()
            if attempt == 2: raise
            time.sleep(3)
    try:
        with c.open_sftp() as sftp:
            with sftp.open('/tmp/overlap_migration.sql', 'wb') as f:
                f.write(MIGRATION)
        _, out, err = c.exec_command(REMOTE, timeout=240)
        text = out.read().decode(errors='replace')
        status = out.channel.recv_exit_status()
        print(text)
        if status:
            print(err.read().decode(errors='replace')[-1500:])
            raise SystemExit('FAILED')
    finally:
        c.close()

if __name__ == '__main__':
    main()
