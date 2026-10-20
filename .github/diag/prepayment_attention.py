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
echo "== services"
for u in booking-web-api booking-bot nginx postgresql; do printf "%s=" $u; systemctl is-active $u; done
echo "== attention endpoint without login (401 = route alive)"
curl -s -o /dev/null -w "local=%{http_code}\n" --max-time 10 http://127.0.0.1:8000/admin/prepayments/attention
curl -sk -o /dev/null -w "public=%{http_code}\n" --max-time 10 --resolve servgo.ru:443:127.0.0.1 https://servgo.ru/api/admin/prepayments/attention
echo "== attention requests in access log (status codes, last 2 days)"
journalctl -u booking-web-api --since "2 days ago" --no-pager -o cat 2>/dev/null | grep -F "/admin/prepayments/attention" | grep -oE '" [0-9]{3}' | sort | uniq -c
echo "== errors (last 2 days, tail)"
journalctl -u booking-web-api --since "2 days ago" --no-pager -o cat 2>/dev/null | grep -nE "Traceback|Error|Exception|error" | tail -15
echo "== last traceback"
journalctl -u booking-web-api --since "2 days ago" --no-pager -o cat 2>/dev/null | awk '/Traceback/{buf=""; on=1} on{buf=buf"\n"$0} /^[A-Za-z_.]+(Error|Exception)/{if(on){last=buf; on=0}} END{print last}' | tail -45
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
