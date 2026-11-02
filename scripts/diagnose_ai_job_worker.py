import os,paramiko,concurrent.futures
c=paramiko.SSHClient();c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('155.212.162.47',username='root',password=os.environ['SERVGO_PASSWORD'],timeout=20)
commands=[
"ss -ltn '( sport = :1089 )'",
"curl --silent --show-error --head --connect-timeout 5 --max-time 12 --proxy socks5h://127.0.0.1:1089 https://cloud.telegram.org",
"curl --silent --show-error --head --connect-timeout 5 --max-time 12 --proxy http://188.120.254.223:8888 https://cloud.telegram.org",
"docker exec ai-job-research-worker node --help"
]
def run(cmd):
 i,o,e=c.exec_command(cmd,timeout=20);i.close();out=o.read().decode();err=e.read().decode();o.close();e.close()
 if 'node --help' in cmd:out='\n'.join(l for l in out.splitlines() if 'proxy' in l.lower())
 return cmd,out[-4000:],err[-2000:]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 for cmd,out,err in pool.map(run,commands):print(cmd,'\n',out,'\n',err)
c.close()
