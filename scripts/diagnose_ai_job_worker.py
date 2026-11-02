import os,paramiko
c=paramiko.SSHClient();c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('155.212.162.47',username='root',password=os.environ['SERVGO_PASSWORD'],timeout=20)
commands=[
"docker inspect ai-job-research-worker --format '{{json .State}}'",
"docker logs --tail 20 ai-job-research-worker",
"docker exec ai-job-research-worker /app/node_modules/.bin/tgcloud --version",
"docker exec ai-job-research-worker node -e \"fetch('https://cloud.telegram.org').then(r=>console.log('Telegram HTTP',r.status)).catch(e=>console.log('Telegram connection',e.message,e.cause?.code))\"",
"docker exec ai-job-research-worker node -e \"const f=require('fs');console.log('CLI package',f.readFileSync('/app/node_modules/@tgcloud/cli/package.json','utf8'));console.log('project',f.readdirSync('/state/project-next'))\"",
"docker exec ai-job-research-worker sh -c 'ls /app/node_modules/@tgcloud/cli/dist; ls /app/node_modules/@tgcloud/cli'"
]
for cmd in commands:
 _,o,e=c.exec_command(cmd,timeout=40);print(o.read().decode()[-14000:]);print(e.read().decode()[-3000:])
c.close()
