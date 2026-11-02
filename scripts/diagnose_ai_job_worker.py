import os,paramiko,shlex,socket,json
ips=sorted({r[4][0] for r in socket.getaddrinfo('cloud.telegram.org',443,socket.AF_INET,socket.SOCK_STREAM)})
print('Runner Telegram DNS:',ips)
js="""const https=require('https');const ips=IPS;
Promise.all(ips.map(ip=>new Promise(resolve=>{const q=https.get({hostname:'cloud.telegram.org',path:'/',servername:'cloud.telegram.org',lookup:(h,o,cb)=>cb(null,o.all?[{address:ip,family:4}]:ip,4)},r=>{console.log('Verified Telegram TLS',ip,r.statusCode);r.resume();resolve()});q.setTimeout(7000,()=>q.destroy(new Error('timeout')));q.on('error',e=>{console.log('Telegram route',ip,e.code||e.message);resolve()})})));
""".replace('IPS',json.dumps(ips))
c=paramiko.SSHClient();c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('155.212.162.47',username='root',password=os.environ['SERVGO_PASSWORD'],timeout=20)
cmd='docker exec ai-job-research-worker node -e '+shlex.quote(js)
i,o,e=c.exec_command(cmd,timeout=30);i.close();print(o.read().decode()[-6000:]);print(e.read().decode()[-3000:]);o.close();e.close();c.close()
