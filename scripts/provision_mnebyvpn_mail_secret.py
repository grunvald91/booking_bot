"""Provision private shared HMAC key on ServGo; export ONLY RSA-OAEP ciphertext.
The secret never appears in GitHub Actions logs, source files or artifacts.
"""
from __future__ import annotations
import base64
import os
import pathlib
import shlex
import subprocess
import tempfile
from scripts.deploy_business_creation_and_reminders import connect, run

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLIC_KEY = ROOT / "ops" / "mnebyvpn-mail-bridge.pub.pem"
CIPHERTEXT = ROOT / "ops" / "mnebyvpn-mail-bridge.enc.b64"
REMOTE_PUBLIC = "/tmp/mnebyvpn-mail-bridge.pub.pem"
REMOTE_CIPHER = "/tmp/mnebyvpn-mail-bridge.enc"

REMOTE_CODE = r"""
import pathlib,secrets,os,subprocess,urllib.request,time
if os.geteuid()!=0:
    raise RuntimeError('ServGo mail provisioning requires root')
public=pathlib.Path('/tmp/mnebyvpn-mail-bridge.pub.pem')
cipher=pathlib.Path('/tmp/mnebyvpn-mail-bridge.enc')
if not public.is_file() or not public.read_bytes().startswith(b'-----BEGIN PUBLIC KEY-----'):
    raise RuntimeError('Invalid recipient public key')
cfgdir=pathlib.Path('/etc/booking-web-api')
cfgdir.mkdir(mode=0o700,parents=True,exist_ok=True)
cfgdir.chmod(0o700)
secret_file=cfgdir/'mnebyvpn-mail.env'
if secret_file.exists():
    raw=secret_file.read_text().strip()
    name,sep,value=raw.partition('=')
    if sep!='=' or name!='MNEBYVPN_MAIL_GATEWAY_SECRET' or len(value)!=96 or not all(c in '0123456789abcdef' for c in value):
        raise RuntimeError('Existing mail secret is unexpected; refusing overwrite')
    secret=value
else:
    secret=secrets.token_hex(48)
    tmp=secret_file.with_suffix('.tmp')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        f.write('MNEBYVPN_MAIL_GATEWAY_SECRET='+secret+'\n')
        f.flush();os.fsync(f.fileno())
    os.replace(tmp,secret_file)
secret_file.chmod(0o600)
dropdir=pathlib.Path('/etc/systemd/system/booking-web-api.service.d')
dropdir.mkdir(mode=0o755,exist_ok=True)
dropin=dropdir/'70-mnebyvpn-mail.conf'
expected='[Service]\nEnvironmentFile=/etc/booking-web-api/mnebyvpn-mail.env\n'
if dropin.exists() and dropin.read_text()!=expected:
    raise RuntimeError('Existing systemd mail override diverged')
if not dropin.exists():
    dropin.write_text(expected)
    dropin.chmod(0o644)
def sysctl(*args):
    subprocess.run(['systemctl',*args],timeout=80,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
sysctl('daemon-reload')
sysctl('restart','booking-web-api.service')
ready=False
for _ in range(25):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3) as r:
            if r.status==200: ready=True;break
    except Exception: time.sleep(2)
if not ready:raise RuntimeError('API failed after secure mail environment activation')
# The unsigned empty-body request must produce 400 and NEVER 503.
req=urllib.request.Request('http://127.0.0.1:8000/auth/mnebyvpn/email-code',
    method='POST',data=b'',headers={'Content-Type':'application/json'})
try:
    urllib.request.urlopen(req,timeout=8)
    raise RuntimeError('Signed mail route unexpectedly allowed unsigned request')
except urllib.error.HTTPError as exc:
    if exc.code not in (400,401): raise RuntimeError('Mail secret not active in API')
crypto=subprocess.run(['openssl','pkeyutl','-encrypt','-pubin','-inkey',str(public),
    '-pkeyopt','rsa_padding_mode:oaep','-pkeyopt','rsa_oaep_md:sha256'],
    input=secret.encode(),capture_output=True,timeout=10,check=True)
if len(crypto.stdout)!=384:raise RuntimeError('Unexpected RSA-3072 ciphertext size')
cipher.write_bytes(crypto.stdout)
cipher.chmod(0o600)
print('servgo_mail_hmac_active=true')
print('servgo_mail_api_health=200')
print('rsa_oaep_ciphertext_only=true')
"""

def main():
    if not PUBLIC_KEY.is_file():
        raise RuntimeError('Infra public key has not been fetched and checked')
    subprocess.run(['openssl','pkey','-pubin','-in',str(PUBLIC_KEY),'-noout'],
        check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
    if not os.environ.get('SERVGO_PASSWORD'):
        raise RuntimeError('SSH secret unavailable')
    client=connect(os.environ['SERVGO_PASSWORD'])
    sftp=client.open_sftp()
    try:
        sftp.put(str(PUBLIC_KEY),REMOTE_PUBLIC)
        sftp.chmod(REMOTE_PUBLIC,0o600)
        result=run(client,'python3 -c '+shlex.quote(REMOTE_CODE),155)
        if 'servgo_mail_hmac_active=true' not in result:
            raise RuntimeError('Mail service activation was not acknowledged')
        with sftp.open(REMOTE_CIPHER,'rb') as file:
            blob=file.read()
        if len(blob)!=384:
            raise RuntimeError('Unexpected encrypted blob length')
        CIPHERTEXT.parent.mkdir(parents=True,exist_ok=True)
        CIPHERTEXT.write_text(base64.b64encode(blob).decode('ascii')+'\n')
        print('servgo_mail_hmac_active=true; ciphertext_staged_for_GitHub=true')
    finally:
        for file in (REMOTE_PUBLIC,REMOTE_CIPHER):
            try:sftp.remove(file)
            except OSError:pass
        sftp.close()
        client.close()

if __name__=='__main__':
    main()
