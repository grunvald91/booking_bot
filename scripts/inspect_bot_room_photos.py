"""Read-only, redacted room-photo bot flow diagnostics."""
import base64
import hashlib
import logging
import os
import shlex
import time

import paramiko

HOST = "155.212.162.47"
FP = "uQJp3lT4golKb3lsDTCFozGWR1ihlu1w/Oa4cSzCdpU"
logging.getLogger("paramiko").setLevel(logging.CRITICAL)


class PinnedKey(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        fp = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        if fp != FP:
            raise paramiko.SSHException("ServGo SSH host key mismatch")
        client.get_host_keys().add(hostname, key.get_name(), key)


REMOTE = r'''import asyncio, hashlib, json, pathlib, re, subprocess
from sqlalchemy import text
from database.database import async_session_maker
path=pathlib.Path('/opt/booking_bot/bot/handlers/admin.py')
print('admin_sha256='+hashlib.sha256(path.read_bytes()).hexdigest())
for unit in ('booking-bot.service','booking-bot-relay89.service'):
    p=subprocess.run(['systemctl','is-active',unit],capture_output=True,text=True)
    print(unit+'_state='+p.stdout.strip())
p=subprocess.run(['journalctl','-u','booking-bot.service','--since','-8 hours','--no-pager','-o','json'],capture_output=True,text=True,timeout=18)
if p.returncode: raise RuntimeError('journal unavailable')
entries=[json.loads(line) for line in p.stdout.splitlines() if line.strip().startswith('{')]
print('journal_entries='+str(len(entries)))
for i,entry in enumerate(entries):
    msg=str(entry.get('MESSAGE',''))
    if 'emp_add_photo:' in msg or 'emp_photos_done:' in msg or 'edit_emp_photos:' in msg:
        matched=re.search(r'(emp_add_photo|emp_photos_done|edit_emp_photos):',msg)
        print('photo_callback='+str(i)+' kind='+matched.group(1))
    if 'Traceback (most recent call last)' in msg or 'TypeError:' in msg or 'TelegramBadRequest:' in msg:
        block='\n'.join(str(e.get('MESSAGE','')) for e in entries[i:min(i+35,len(entries))])
        frames=re.findall(r'File "[^"\n]*/([^/"\n]+\.py)", line (\d+)',block)
        classes=re.findall(r'(?m)^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)):',block)
        if any('admin.py'==f for f,n in frames) or 'TypeError' in msg:
            print('bot_error='+str(i)+' frames='+','.join(f+':'+n for f,n in frames[-8:])+' types='+','.join(classes[:3]))
async def check():
    async with async_session_maker() as session:
        rows=await session.execute(text("SELECT b.id,e.id,e.photos FROM businesses b JOIN employees e ON e.business_id=b.id WHERE b.name ILIKE '%100boats%' ORDER BY e.id"))
        for b_id,e_id,raw in rows:
            try: count=len(json.loads(raw)) if raw else 0
            except (ValueError,TypeError): count=-1
            print('demo_room business_id='+str(b_id)+' employee_id='+str(e_id)+' photo_count='+str(count))
asyncio.run(check())'''


def main():
    password = os.environ.get("SERVGO_PASSWORD")
    if not password:
        raise RuntimeError("Missing GitHub SSH secret")
    for attempt in range(3):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(PinnedKey())
        try:
            client.connect(HOST, port=22, username="root", password=password,
                           allow_agent=False, look_for_keys=False, timeout=12,
                           banner_timeout=25, auth_timeout=15)
            _, stdout, _ = client.exec_command("cd /opt/booking_bot && ./venv/bin/python -c " + shlex.quote(REMOTE), timeout=40)
            result = stdout.read().decode("utf-8", "replace")
            if stdout.channel.recv_exit_status():
                raise RuntimeError("Read-only bot photo probe failed; stderr suppressed")
            print(result)
            return
        except (paramiko.SSHException, OSError, EOFError):
            if attempt == 2:
                raise RuntimeError("ServGo SSH unavailable") from None
            time.sleep(3)
        finally:
            client.close()


if __name__ == "__main__":
    main()
