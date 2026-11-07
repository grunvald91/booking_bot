"""Scoped Postfix outgoing SMTP HELO normalization with backup/rollback.
Does not change DNS, SPF, DKIM, DMARC, mail account or certificate.
"""
from __future__ import annotations
import os
import shlex
from scripts.deploy_business_creation_and_reminders import connect,run

OLD='artur.grunvald1991.fvds.ru'
NEW='mail.servgo.ru'
CONF='/etc/postfix/main.cf'
BACKUP='/etc/postfix/main.cf.mnebyvpn-helo-20261107.bak'

def main()->None:
    pwd=os.environ.get('SERVGO_PASSWORD','')
    if not pwd:raise RuntimeError('ServGo SSH secret absent')
    client=connect(pwd)
    changed=False
    try:
        hostname=run(client,'postconf -h myhostname')
        current=run(client,'postconf -h smtp_helo_name')
        if hostname!=NEW:raise RuntimeError('Postfix primary identity does not match expected mail hostname')
        if current==NEW:
            print('smtp_helo_already_aligned=true')
            return
        if current!=OLD:raise RuntimeError('SMTP HELO configuration differs; refusing overwrite')
        if os.environ.get('APPLY','false').lower()!='true':
            print('smtp_helo_preflight=passed')
            return
        run(client,'test ! -e '+shlex.quote(BACKUP)+' && cp -p '+
            shlex.quote(CONF)+' '+shlex.quote(BACKUP))
        run(client,'postconf -e '+shlex.quote('smtp_helo_name = '+NEW))
        changed=True
        run(client,'postfix check',20)
        run(client,'postfix reload',25)
        if run(client,'postconf -h smtp_helo_name')!=NEW:
            raise RuntimeError('SMTP HELO was not updated')
        print('smtp_helo_aligned_with_postfix_hostname=true')
        print('smtp_config_backup=created')
    except Exception:
        if changed:
            try:
                run(client,'cp -p '+shlex.quote(BACKUP)+' '+shlex.quote(CONF)+
                  ' && postfix check && postfix reload',35)
                print('smtp_helo_rollback=restored')
            except Exception:
                print('smtp_helo_rollback=manual_inspection_needed')
        raise
    finally:
        client.close()
if __name__=='__main__':main()
