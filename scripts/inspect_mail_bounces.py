"""Read-only diagnosis of recurring 'Undelivered Mail Returned to Sender' bounces on the ServGo mail server.

Nothing on the server is changed. Recipient addresses are masked (local part hidden), message bodies are
never printed - only counts, delivery status codes, remote server replies, original subjects and the
sending application hints.
"""
import base64
import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.deploy_business_creation_and_reminders import connect  # noqa: E402

REMOTE = r'''
import collections, email, email.policy, glob, os, re, subprocess, time

def sh(cmd, timeout=40):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return p.stdout.strip()
    except Exception as exc:
        return "ERR " + type(exc).__name__

def mask(addr):
    addr = addr.strip().strip("<>")
    if "@" not in addr:
        return addr[:3] + "***"
    local, dom = addr.rsplit("@", 1)
    return (local[:2] + "***@" + dom)

print("== POSTFIX ==")
print("postfix_active:", sh("systemctl is-active postfix"))
print("queue_tail:", sh("postqueue -p 2>/dev/null | tail -1"))
print("main_cf_relevant:", sh("postconf -n 2>/dev/null | grep -E '^(myhostname|myorigin|inet_interfaces|relayhost|smtpd_recipient_restrictions|mydestination|virtual_mailbox_domains|bounce_|notify_classes|maximal_queue_lifetime) '"))

print("== MAIL LOG STATUS COUNTS (last 3 days) ==")
log = sh("journalctl -u postfix@- -u postfix --since -3d --no-pager -o short-iso 2>/dev/null | grep -E 'status=(bounced|deferred)' | tail -400", 60)
if not log:
    log = sh("tail -n 4000 /var/log/mail.log 2>/dev/null | grep -E 'status=(bounced|deferred)' | tail -400", 60)
status = collections.Counter(); reasons = collections.Counter(); doms = collections.Counter(); hours = collections.Counter()
for line in log.splitlines():
    m = re.search(r"to=<([^>]*)>.*?status=(\w+) \((.*)\)", line)
    if not m:
        continue
    to, st, why = m.groups()
    dom = to.rsplit("@", 1)[-1] if "@" in to else "?"
    status[st] += 1
    doms[dom] += 1
    why = re.sub(r"[\w.+-]+@[\w.-]+", "<addr>", why)
    reasons[(st, why[:170])] += 1
    h = re.match(r"(\d{4}-\d\d-\d\dT\d\d)", line)
    if h:
        hours[h.group(1)] += 1
print("status:", dict(status))
print("top_domains:", doms.most_common(10))
for (st, why), n in reasons.most_common(8):
    print("REASON", n, st, why)
print("by_hour:", sorted(hours.items())[-24:])

print("== SENDING SOURCES ==")
print("sasl_or_pickup_clients:", sh("journalctl -u postfix --since -1d --no-pager 2>/dev/null | grep -E 'client=' | sed -E 's/.*client=([^ ]*).*/\\1/' | sort | uniq -c | sort -rn | head -5"))
print("from_senders:", sh("journalctl -u postfix --since -1d --no-pager 2>/dev/null | grep -E ' from=<' | sed -E 's/.* from=<([^>]*)>.*/\\1/' | sed -E 's/^[^@]*@/***@/' | sort | uniq -c | sort -rn | head -5"))
print("cron_hourly_entries:", sh("grep -rhE 'mail|smtp|remind|notify' /etc/cron* /var/spool/cron 2>/dev/null | grep -v '^#' | head -10"))
print("timers:", sh("systemctl list-timers --all --no-pager 2>/dev/null | grep -iE 'mail|remind|notif|servgo|booking' | head"))
print("units:", sh("systemctl list-units --type=service --state=running --no-pager --plain 2>/dev/null | awk '{print $1}' | grep -iE 'mail|servgo|booking|growth|postfix|dovecot'"))

print("== BOUNCE MESSAGES IN MAILBOX (last 3 days) ==")
dirs = [d for d in ("/var/mail", "/var/vmail", "/home", "/var/spool/mail") if os.path.isdir(d)]
files = []
for d in dirs:
    out = sh("find %s -type f -mtime -3 -path '*/new/*' -o -type f -mtime -3 -path '*/cur/*' 2>/dev/null | head -400" % d, 60)
    files += [f for f in out.splitlines() if f]
files = files[:400]
subj = collections.Counter(); diag = collections.Counter(); orig_from = collections.Counter(); camp = collections.Counter(); rcpt = collections.Counter(); seen = 0
for f in files:
    try:
        with open(f, "rb") as fh:
            msg = email.message_from_binary_file(fh, policy=email.policy.default)
    except Exception:
        continue
    if "MAILER-DAEMON" not in str(msg.get("From", "")).upper():
        continue
    seen += 1
    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "message/delivery-status":
            for blk in part.get_payload():
                fr = str(blk.get("Final-Recipient", "")).split(";")[-1]
                if fr:
                    rcpt[mask(fr)] += 1
                d = str(blk.get("Diagnostic-Code", ""))
                d = re.sub(r"[\w.+-]+@[\w.-]+", "<addr>", d)
                if d:
                    diag[(str(blk.get("Status", "")), d[:200])] += 1
        elif ct in ("text/rfc822-headers", "message/rfc822"):
            payload = part.get_payload()
            hdr = payload[0] if isinstance(payload, list) and payload else None
            raw = str(hdr) if hdr is not None else str(payload)
            for line in raw.splitlines()[:60]:
                low = line.lower()
                if low.startswith("subject:"):
                    subj[line[8:].strip()[:90]] += 1
                elif low.startswith("from:"):
                    orig_from[re.sub(r"^[^@]*@", "***@", line[5:].strip())[:60]] += 1
                elif low.startswith("x-servgo-campaign"):
                    camp["campaign_mail"] += 1
print("bounce_messages_parsed:", seen, "of", len(files), "files scanned")
print("recipients_masked_top:", rcpt.most_common(12))
for (st, d), n in diag.most_common(8):
    print("DIAG", n, st, d)
print("original_subjects:", subj.most_common(8))
print("original_from:", orig_from.most_common(5))
print("from_campaign_worker:", dict(camp))
'''


def main():
    password = os.environ.get("SERVGO_PASSWORD")
    if not password:
        raise RuntimeError("Missing SSH secret")
    client = connect(password)
    try:
        encoded = base64.b64encode(REMOTE.encode()).decode()
        cmd = "python3 -c " + shlex.quote("import base64;exec(base64.b64decode('" + encoded + "'))")
        _, out, _ = client.exec_command(cmd, timeout=170)
        print(out.read().decode("utf-8", "replace"))
    finally:
        client.close()


if __name__ == "__main__":
    main()
