"""Install only the isolated worker and its nginx location; no app restarts."""
import os
import shlex
import time
from pathlib import Path
import paramiko

host = os.environ.get('SERVER_HOST', '155.212.162.47')
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, port=int(os.environ.get('SERVER_PORT', '22')), username=os.environ.get('SERVER_USER', 'root'), password=os.environ['SERVGO_PASSWORD'], timeout=20)

def run(command, timeout=120):
    stdin, out, err = client.exec_command(command, timeout=timeout)
    stdin.close()
    output, error = out.read().decode(), err.read().decode()
    code = out.channel.recv_exit_status()
    out.close(); err.close()
    if output: print(output[-10000:])
    if error: print(error[-3000:])
    if code: raise RuntimeError('Worker host command failed with status ' + str(code))
    return output

try:
    run('install -d -m 0755 /opt/ai-job-worker-build/worker && install -d -m 0700 -o 1000 -g 1000 /opt/ai-job-worker-state')
    with client.open_sftp() as sftp:
        for source, target in [('server.mjs', 'worker/server.mjs'), ('Dockerfile', 'worker/Dockerfile'), ('package.json', 'package.json'), ('package-lock.json', 'package-lock.json')]:
            sftp.put(str(Path('ops/ai-job-worker') / source), '/opt/ai-job-worker-build/' + target)
    run('docker build -f /opt/ai-job-worker-build/worker/Dockerfile -t ai-job-worker:20261102 /opt/ai-job-worker-build', 300)
    existing = run("docker ps -a --filter name='^/ai-job-research-worker$' --format '{{.Names}}'")
    if not existing.strip():
        run('docker run -d --name ai-job-research-worker --restart unless-stopped --memory=256m --memory-swap=384m --cpus=0.5 --pids-limit=64 --security-opt=no-new-privileges --cap-drop=ALL --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --log-opt max-size=5m --log-opt max-file=2 -v /opt/ai-job-worker-state:/state -p 127.0.0.1:8793:8793 ai-job-worker:20261102')
    run("python3 - <<'REMOTE'\nimport urllib.request,time\nfor n in range(20):\n try:\n  print(urllib.request.urlopen('http://127.0.0.1:8793/health',timeout=2).read().decode());break\n except Exception:\n  if n==19:raise\n  time.sleep(1)\nREMOTE")
    # Match the observed TLS vhost exactly and preserve the original for rollback.
    remote = r'''import pathlib,subprocess,urllib.request
path=pathlib.Path('/etc/nginx/sites-enabled/webapp')
old=path.read_text()
marker='    server_name servgo.ru www.servgo.ru 155.212.162.47;'
include='    include /etc/nginx/snippets/ai-job-worker.conf;'
assert marker in old and '/etc/letsencrypt/live/servgo.ru/fullchain.pem' in old
snippet=pathlib.Path('/etc/nginx/snippets/ai-job-worker.conf')
previous=snippet.read_text() if snippet.exists() else None
snippet.write_text('location ^~ /_ai_job_worker/ {\n    client_max_body_size 16m;\n    access_log off;\n    proxy_pass http://127.0.0.1:8793/;\n    proxy_set_header Host $host;\n    proxy_connect_timeout 3s;\n    proxy_read_timeout 60s;\n}\n')
backup=pathlib.Path('/opt/ai-job-worker-state/nginx-webapp-before.conf')
if not backup.exists():backup.write_text(old)
try:
 if include not in old:path.write_text(old.replace(marker,marker+'\n'+include,1))
 subprocess.run(['nginx','-t'],check=True)
 subprocess.run(['systemctl','reload','nginx'],check=True)
 health=urllib.request.urlopen('https://servgo.ru/_ai_job_worker/health',timeout=15).read().decode()
 print('Worker HTTPS:',health)
 root=urllib.request.urlopen('https://servgo.ru/',timeout=15)
 print('ServGo root HTTP:',root.status)
except Exception:
 path.write_text(old)
 if previous is None:snippet.unlink(missing_ok=True)
 else:snippet.write_text(previous)
 subprocess.run(['nginx','-t'],check=True)
 subprocess.run(['systemctl','reload','nginx'],check=True)
 raise
'''
    run('python3 - <<\'REMOTE\'\n' + remote + '\nREMOTE', 60)
finally:
    client.close()
