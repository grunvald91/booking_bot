"""Send one narrowly scoped MNEBYVPN SMTP acceptance test from existing ServGo API.

Reads production SMTP settings from the running API process. Never logs
passwords or message recipient. Does not deploy code, alter DB or restart API.
"""
from __future__ import annotations

import os

from scripts.deploy_business_creation_and_reminders import connect
from scripts.deploy_vk_id_guarded import remote_python

TEST_ID = "MNEBYVPN-20261107-mail-gate-v1"

REMOTE_CODE = r"""
import os, pathlib, ssl, smtplib
from email.message import EmailMessage

host=os.getenv('SMTP_HOST','')
sender='mnebyvpn@servgo.ru'
receiver=os.getenv('MNEBYVPN_MAIL_TEST_RECIPIENT','')
if not receiver or '@' not in receiver:
    raise RuntimeError('SMTP test recipient not configured')
if not host or not os.getenv('SMTP_FROM_EMAIL'):
    raise RuntimeError('Existing ServGo SMTP is not configured')
port=int(os.getenv('SMTP_PORT','587'))
is_ssl=os.getenv('SMTP_USE_SSL','').lower() in ('1','true','yes','on')
loopback=host.lower().strip() in ('localhost','127.0.0.1','::1')
tls_setting=os.getenv('SMTP_STARTTLS','').lower()
starttls=(tls_setting in ('1','true','yes','on') if tls_setting else not is_ssl and not loopback)
if not is_ssl and not starttls and not loopback:
    raise RuntimeError('Refuse unencrypted remote SMTP')
marker=pathlib.Path('/var/tmp/mnebyvpn-mail-preflight-20261107')
if marker.exists():
    print('SMTP_TEST=previously_submitted')
else:
    msg=EmailMessage()
    msg['From']='MNEBYVPN <'+sender+'>'
    msg['To']=receiver
    msg['Subject']='MNEBYVPN - SMTP verification 2026-11-07'
    msg.set_content('MNEBYVPN SMTP test. No login code or VPN subscription is attached.\n')
    if is_ssl:
        smtp=smtplib.SMTP_SSL(host,port,timeout=12,context=ssl.create_default_context())
    else:
        smtp=smtplib.SMTP(host,port,timeout=12)
    try:
        smtp.ehlo()
        if starttls and not is_ssl:
            smtp.starttls(context=ssl.create_default_context());smtp.ehlo()
        username=os.getenv('SMTP_USERNAME','')
        if username:
            smtp.login(username,os.getenv('SMTP_PASSWORD',''))
        refused=smtp.send_message(msg)
        if refused:
            raise RuntimeError('SMTP refused one or more recipients')
    finally:
        try: smtp.quit()
        except Exception: smtp.close()
    marker.write_text('accepted\n')
    marker.chmod(0o600)
    print('SMTP_TEST=accepted_by_mail_server')
print('SMTP_FROM_CONFIGURED=true')
print('SMTP_SENDER_USED=mnebyvpn@servgo.ru')
"""

def main() -> None:
    password=os.environ.get("SERVGO_PASSWORD","")
    recipient=os.environ.get("MNEBYVPN_MAIL_TEST_RECIPIENT","")
    if not password or not recipient:
        raise RuntimeError("Preflight credentials/recipient unavailable")
    # remote_python executes with current API secrets, never echoes them.
    client=connect(password)
    try:
        # recipient is fixed to this owner's verification mailbox, never
        # passed from arbitrary request inputs or public users.
        import re
        if not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}",recipient):
            raise RuntimeError("Unsafe SMTP test recipient")
        code="os.environ['MNEBYVPN_MAIL_TEST_RECIPIENT']="+repr(recipient)+"\n"+REMOTE_CODE
        out=remote_python(client,code,75)
        if "SMTP_TEST=accepted_by_mail_server" not in out and "SMTP_TEST=previously_submitted" not in out:
            raise RuntimeError("No SMTP acceptance confirmation")
        print(out)
    finally:
        client.close()

if __name__ == "__main__":
    main()
