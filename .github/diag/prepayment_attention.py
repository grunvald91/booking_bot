"""Read-only: why /admin/prepayments/attention fails. Prints redacted web API log lines only."""
import base64, hashlib, os, re, time
import paramiko

HOST, FP = '155.212.162.47', 'uQJp3lT4golKb3lsDTCFozGWR1ihlu1w/Oa4cSzCdpU'
REDACT = re.compile(r'(\d{6,12}:[A-Za-z0-9_-]{20,})|((?:password|passwd|secret|token|authorization|bearer)\S*\s*[=:]\s*\S+)|(postgres(?:ql)?(?:\+\w+)?://\S+)', re.I)

class Pinned(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        if base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=') != FP:
            raise paramiko.SSHException('Host key mismatch')
        client.get_host_keys().add(hostname, key.get_name(), key)

REMOTE = r'''
echo "== HTTP 500 by path (last 2 days)"
journalctl -u booking-web-api --since "2 days ago" --no-pager -o cat 2>/dev/null | grep -E '" 500' | grep -oE '"(GET|POST|PUT|PATCH|DELETE) [^ ?"]+' | sed -E 's#/[0-9]+#/N#g' | sort | uniq -c | sort -rn | head -25
echo "== HTTP 2xx booking-related (last 2 days)"
journalctl -u booking-web-api --since "2 days ago" --no-pager -o cat 2>/dev/null | grep -E '" 20[01]' | grep -oE '"(GET|POST) [^ ?"]*(book|slot|schedule)[^ ?"]*' | sed -E 's#/[0-9]+#/N#g' | sort | uniq -c | sort -rn | head -10
echo "== first 500 time"
journalctl -u booking-web-api --since "4 days ago" --no-pager 2>/dev/null | grep -E 'resource_duration_minutes does not exist' | head -1 | cut -c1-16
echo "== bot errors (last 2 days)"
journalctl -u booking-bot --since "2 days ago" --no-pager -o cat 2>/dev/null | grep -cE 'resource_duration_minutes|occupies_resource'
echo "== DB schema (read-only)"
cd /tmp && sudo -u postgres psql -d booking_bot -At -c "select column_name from information_schema.columns where table_name='bookings' and column_name in ('resource_duration_minutes','occupies_resource','duration_minutes')" 2>&1 | head
sudo -u postgres psql -d booking_bot -At -c "select 'btree_gist='||count(*) from pg_extension where extname='btree_gist'" 2>&1
sudo -u postgres psql -d booking_bot -At -c "select 'available_btree_gist='||count(*) from pg_available_extensions where name='btree_gist'" 2>&1
sudo -u postgres psql -d booking_bot -At -c "select 'bookings_total='||count(*) from bookings" 2>&1
echo "== active overlaps that would block the DB constraint (read-only)"
sudo -u postgres psql -d booking_bot -At -c "select 'overlap_pairs='||count(*) from bookings a join bookings b on a.employee_id=b.employee_id and a.id<b.id and a.booking_date=b.booking_date join services sa on sa.id=a.service_id join services sb on sb.id=b.service_id where a.employee_id is not null and a.status in ('pending','confirmed','pending_prepayment','prepayment_sent','prepayment_confirmed') and b.status in ('pending','confirmed','pending_prepayment','prepayment_sent','prepayment_confirmed') and not coalesce(sa.is_additional,false) and not coalesce(sb.is_additional,false) and tsrange(a.booking_date+a.booking_time, a.booking_date+a.booking_time+coalesce(a.duration_minutes,sa.duration_minutes,30)*interval '1 minute','[)') && tsrange(b.booking_date+b.booking_time, b.booking_date+b.booking_time+coalesce(b.duration_minutes,sb.duration_minutes,30)*interval '1 minute','[)')" 2>&1
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
        _, out, err = c.exec_command(REMOTE, timeout=90)
        text = out.read().decode(errors='replace') + err.read().decode(errors='replace')
        print(REDACT.sub('[REDACTED]', text))
    finally:
        c.close()

if __name__ == '__main__':
    main()
