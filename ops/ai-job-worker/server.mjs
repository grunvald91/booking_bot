import http from 'node:http';
import {DatabaseSync} from 'node:sqlite';
import {mkdirSync,existsSync,readFileSync,writeFileSync,renameSync,rmSync} from 'node:fs';
import {createHash,randomBytes,generateKeyPairSync,createDecipheriv,createCipheriv,privateDecrypt,timingSafeEqual} from 'node:crypto';
import {spawn} from 'node:child_process';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

export function createWorker({stateDir,cli,appId='8737599643',fetcher=fetch,runCli=null,probeDelay=31000}={}){
 mkdirSync(stateDir,{recursive:true,mode:0o700});
 const credentialsFile=join(stateDir,'credentials.json'),privateFile=join(stateDir,'bootstrap-private.pem'),keyFile=join(stateDir,'data-key');
 if(!existsSync(privateFile)){
  const pair=generateKeyPairSync('rsa',{modulusLength:3072,publicKeyEncoding:{type:'spki',format:'pem'},privateKeyEncoding:{type:'pkcs8',format:'pem'}});
  writeFileSync(privateFile,pair.privateKey,{mode:0o600});writeFileSync(join(stateDir,'bootstrap-public.pem'),pair.publicKey,{mode:0o644});
 }
 if(!existsSync(keyFile))writeFileSync(keyFile,randomBytes(32),{mode:0o600});
 const dataKey=readFileSync(keyFile);
 const seal=value=>{const iv=randomBytes(12),c=createCipheriv('aes-256-gcm',dataKey,iv);const body=Buffer.concat([c.update(JSON.stringify(value)),c.final()]);return JSON.stringify({iv:iv.toString('base64'),tag:c.getAuthTag().toString('base64'),body:body.toString('base64')});};
 const open=value=>{const v=JSON.parse(value),d=createDecipheriv('aes-256-gcm',dataKey,Buffer.from(v.iv,'base64'));d.setAuthTag(Buffer.from(v.tag,'base64'));return JSON.parse(Buffer.concat([d.update(Buffer.from(v.body,'base64')),d.final()]).toString());};
 let credentials=existsSync(credentialsFile)?JSON.parse(readFileSync(credentialsFile)):null;
 const db=new DatabaseSync(join(stateDir,'queue.sqlite'));
 db.exec(`PRAGMA journal_mode=WAL;
 CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,user_id INTEGER,kind TEXT,payload TEXT,status TEXT,next_at INTEGER,step INTEGER DEFAULT 0,failures INTEGER DEFAULT 0,result TEXT,created_at INTEGER);
 CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,user_id INTEGER,request TEXT,status TEXT,response TEXT,created_at INTEGER);
 CREATE TABLE IF NOT EXISTS waiters(request_id TEXT,task_id TEXT,PRIMARY KEY(request_id,task_id));
 UPDATE tasks SET status='queued',next_at=0 WHERE status='running';
 UPDATE requests SET status='queued' WHERE status='running';`);
 if(!db.prepare('PRAGMA table_info(requests)').all().some(c=>c.name==='provider'))db.exec('ALTER TABLE requests ADD COLUMN provider TEXT');
 const query=(sql,...args)=>db.prepare(sql).all(...args),one=(sql,...args)=>db.prepare(sql).get(...args),exec=(sql,...args)=>db.prepare(sql).run(...args);
 let closed=false,ticking=false,bootstrapping=false;const network=new Set();
 function authorized(req){
  const expected=credentials&&Buffer.from('Bearer '+credentials.key),actual=Buffer.from(req.headers.authorization||'');
  return expected&&expected.length===actual.length&&timingSafeEqual(expected,actual);
 }
 async function invoke(args,token=credentials?.token,cwd=join(stateDir,'project')){
  if(runCli)return runCli(args,token,cwd);
  return new Promise((resolveResult,reject)=>{
   const child=spawn(cli,args,{cwd,env:{...process.env,TGCLOUD_TOKEN:token},stdio:['ignore','pipe','pipe']});
   let output='',size=0;
   const timer=setTimeout(()=>{child.kill('SIGKILL');reject(new Error('CLI timeout'));},35000);
   child.stdout.on('data',chunk=>{size+=chunk.length;if(size<2*1024*1024)output+=chunk.toString();});
   // Deliberately do not forward CLI output: it can contain request arguments.
   child.stderr.resume();child.on('error',e=>{clearTimeout(timer);reject(e);});
   child.on('exit',code=>{clearTimeout(timer);code===0?resolveResult(output):reject(new Error('CLI invocation failed'));});
  });
 }
 async function bootstrap(envelope){
  const key=privateDecrypt({key:readFileSync(privateFile),oaepHash:'sha256'},Buffer.from(envelope.key,'base64'));
  const d=createDecipheriv('aes-256-gcm',key,Buffer.from(envelope.iv,'base64'));d.setAuthTag(Buffer.from(envelope.tag,'base64'));
  const input=JSON.parse(Buffer.concat([d.update(Buffer.from(envelope.body,'base64')),d.final()]).toString());
  if(typeof input.token!=='string'||typeof input.key!=='string'||input.key.length<40||!input.files)throw new Error('Invalid bootstrap');
  const stage=join(stateDir,'project-next');rmSync(stage,{recursive:true,force:true});mkdirSync(stage,{recursive:true,mode:0o700});
  for(const [name,content] of Object.entries(input.files)){
   if(!/^(?:tgcloud\/(?:lib\/[a-zA-Z0-9_./-]+\.js|handlers\/[a-zA-Z0-9_-]+\.js|schema\.js)|tgcloud\.jsonc|package\.json)$/.test(name)||name.includes('..')||typeof content!=='string')throw new Error('Invalid project path');
   const dest=resolve(stage,name);mkdirSync(resolve(dest,'..'),{recursive:true});writeFileSync(dest,content,{mode:0o600});
  }
  const proof=await invoke(['--no-pager','webhook'],input.token,stage);
  // Only possession of this bot's administrative CLI token can initialize or
  // rotate the worker. Public bootstrap encryption keys grant no authority.
  if(!proof.includes('app'+appId+'/webhook'))throw new Error('Wrong bot');
  const project=join(stateDir,'project'),old=join(stateDir,'project-old');
  rmSync(old,{recursive:true,force:true});if(existsSync(project))renameSync(project,old);renameSync(stage,project);
  credentials={token:input.token,key:input.key};writeFileSync(credentialsFile,JSON.stringify(credentials),{mode:0o600});
 }
 function validTask(task){return task&&typeof task.id==='string'&&task.id.length<=180&&Number.isSafeInteger(task.userId)&&task.userId>0&&['search','list','detail','draft','test','probe'].includes(task.kind)&&task.params&&typeof task.params==='object';}
 async function route(req,res){
  const url=new URL(req.url,'http://worker');const send=(status,value)=>{res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(value));};
  if(req.method==='GET'&&url.pathname==='/health')return send(200,{ok:true,ready:Boolean(credentials),running:query("SELECT id FROM tasks WHERE status IN ('queued','waiting','running')").length});
  if(req.method==='GET'&&url.pathname==='/bootstrap/key')return send(200,{publicKey:readFileSync(join(stateDir,'bootstrap-public.pem'),'utf8')});
  if(url.pathname!=='/bootstrap'&&!authorized(req))return send(403,{error:'unauthorized'});
  let size=0,body='';for await(const chunk of req){size+=chunk.length;if(size>16*1024*1024)return send(413,{error:'body too large'});body+=chunk;}
  const input=body?JSON.parse(body):{};
  if(req.method==='POST'&&url.pathname==='/bootstrap'){
   if(bootstrapping)return send(409,{error:'bootstrap busy'});bootstrapping=true;
   try{await bootstrap(input);return send(200,{ready:true});}finally{bootstrapping=false;}
  }
  if(req.method==='POST'&&url.pathname==='/enqueue'){
   if(!validTask(input))return send(400,{error:'invalid task'});
   const existing=one('SELECT * FROM tasks WHERE id=?',input.id);
   if(existing&&existing.user_id!==input.userId)return send(403,{error:'owner mismatch'});
   if(input.kind==='search'&&input.params.fresh)exec("UPDATE tasks SET status='cancelled' WHERE user_id=? AND kind='search' AND id<>?",input.userId,input.id);
   if(!existing)exec("INSERT INTO tasks(id,user_id,kind,payload,status,next_at,created_at) VALUES(?,?,?,?, 'queued',0,?)",input.id,input.userId,input.kind,JSON.stringify(input),Date.now());
   else if(['done','paused','failed','cancelled'].includes(existing.status))exec("UPDATE tasks SET payload=?,status='queued',next_at=0,failures=0 WHERE id=?",JSON.stringify(input),input.id);
   return send(200,{id:input.id});
  }
  if(req.method==='POST'&&url.pathname==='/cancel'){
   exec("UPDATE tasks SET status='cancelled' WHERE id=? AND user_id=?",input.id,input.userId);return send(200,{cancelled:true});
  }
  if(req.method==='POST'&&url.pathname==='/fetch'){
   const task=one('SELECT * FROM tasks WHERE id=? AND user_id=?',input.taskId,input.userId);
   if(!task||task.status==='cancelled')return send(403,{error:'unknown task'});
   const probe=input.url==='worker://delay'&&task.kind==='probe';
   if(!probe){const target=new URL(input.url);if(target.protocol!=='https:'||!['openrouter.ai','api.claudehub.fun'].includes(target.hostname)||target.username||target.password||target.port)return send(400,{error:'provider not allowed'});}
   const id=createHash('sha256').update(JSON.stringify([input.userId,input.url,input.options])).digest('hex');
   let existing=one('SELECT * FROM requests WHERE id=?',id);
   if(existing?.status==='done'){
    const cached=open(existing.response);
    if(cached.status<400||existing.created_at>Date.now()-60000)return send(200,cached);
    exec('DELETE FROM waiters WHERE request_id=?',id);exec('DELETE FROM requests WHERE id=?',id);existing=null;
   }
   if(!existing)exec("INSERT INTO requests(id,user_id,request,status,created_at,provider) VALUES(?,?,?,'queued',?,?)",id,input.userId,seal({url:input.url,options:input.options,probe}),Date.now(),probe?'worker':new URL(input.url).hostname);
   exec('INSERT OR IGNORE INTO waiters(request_id,task_id) VALUES(?,?)',id,input.taskId);
   return send(200,{pending:true});
  }
  if(req.method==='POST'&&url.pathname==='/status'){
   const task=one('SELECT id,status,step,failures,result FROM tasks WHERE id=? AND user_id=?',input.id,input.userId);
   if(task)task.providers=query('SELECT r.provider,r.status,r.response FROM requests r JOIN waiters w ON w.request_id=r.id WHERE w.task_id=?',input.id).map(r=>({host:r.provider,state:r.status,httpStatus:r.response?open(r.response).status:null}));
   return send(task?200:404,task||{error:'not found'});
  }
  return send(404,{error:'not found'});
 }
 async function doRequest(row){
  network.add(row.id);exec("UPDATE requests SET status='running' WHERE id=?",row.id);
  try{
   const input=open(row.request);let result;
   if(input.probe){const start=Date.now();await new Promise(r=>setTimeout(r,probeDelay));result={status:200,body:JSON.stringify({probe:true,elapsedMs:Date.now()-start}),headers:{}};}
   else{
    const response=await fetcher(input.url,{...input.options,redirect:'error',signal:AbortSignal.timeout(180000)});
    const body=await response.text();if(body.length>4*1024*1024)throw new Error('Provider response too large');
    result={status:response.status,body,headers:{'retry-after':response.headers.get('retry-after')}};
   }
   exec("UPDATE requests SET status='done',request=NULL,response=? WHERE id=?",seal(result),row.id);
  }catch{
   exec("UPDATE requests SET status='done',request=NULL,response=? WHERE id=?",seal({status:502,body:'{"error":{"message":"Background provider request failed"}}',headers:{}}),row.id);
  }finally{
   exec("UPDATE tasks SET status='queued',next_at=0 WHERE id IN (SELECT task_id FROM waiters WHERE request_id=?) AND status='waiting'",row.id);
   network.delete(row.id);
  }
 }
 async function tick(){
  if(closed||ticking||bootstrapping||!credentials)return;ticking=true;
  try{
   for(const row of query("SELECT * FROM requests WHERE status='queued' ORDER BY created_at LIMIT 2"))if(network.size<2&&!network.has(row.id))void doRequest(row);
   const task=one("SELECT * FROM tasks WHERE status='queued' AND next_at<=? ORDER BY next_at,created_at LIMIT 1",Date.now());
   if(!task)return;
   // All persisted mutations and Bot API sends are serialized through the CLI.
   exec("UPDATE tasks SET status='running',step=step+1 WHERE id=?",task.id);
   try{
    const output=await invoke(['--no-pager','run','lib/background',JSON.stringify({id:task.id,userId:task.user_id,step:task.step+1})]);
    const match=output.match(/WORKER_RESULT (\{[^\r\n]*\})/);if(!match)throw new Error('Missing worker result');
    const result=JSON.parse(match[1]);
    if(one('SELECT status FROM tasks WHERE id=?',task.id)?.status==='cancelled')return;
    const pending=one("SELECT r.id FROM requests r JOIN waiters w ON w.request_id=r.id WHERE w.task_id=? AND r.status<>'done'",task.id);
    exec('UPDATE tasks SET status=?,next_at=?,result=?,failures=0 WHERE id=?',result.failed?'failed':result.done?'done':result.waiting&&pending?'waiting':'queued',result.nextAt||Date.now()+(result.busy?30000:2000),JSON.stringify(result),task.id);
   }catch{
    const failures=task.failures+1;
    exec('UPDATE tasks SET status=?,next_at=?,failures=? WHERE id=?',failures>=8?'failed':'queued',Date.now()+Math.min(180000,failures*15000),failures,task.id);
    console.error('background invocation failed',task.kind,'attempt',failures);
   }
  }finally{ticking=false;}
 }
 const server=http.createServer((req,res)=>{route(req,res).catch(()=>{if(!res.headersSent)res.writeHead(400,{'Content-Type':'application/json'});res.end('{"error":"request failed"}');});});
 const timer=setInterval(()=>void tick(),1000);timer.unref();
 const cleanup=setInterval(()=>{
  const cutoff=Date.now()-86400000;
  exec("DELETE FROM waiters WHERE request_id IN (SELECT id FROM requests WHERE status='done' AND created_at<?)",cutoff);
  exec("DELETE FROM requests WHERE status='done' AND created_at<?",cutoff);
  exec("DELETE FROM tasks WHERE status IN ('done','cancelled','failed','paused') AND created_at<?",Date.now()-7*86400000);
 },3600000);cleanup.unref();
 return {server,tick,db,close:()=>{closed=true;clearInterval(timer);clearInterval(cleanup);server.close();if(!ticking&&!network.size)db.close();}};
}
if(process.argv[1]&&fileURLToPath(import.meta.url)===resolve(process.argv[1])){
 const worker=createWorker({stateDir:process.env.STATE_DIR||'/state',cli:process.env.TGCLOUD_CLI||'/app/node_modules/.bin/tgcloud'});
 worker.server.listen(Number(process.env.PORT)||8793,'0.0.0.0',()=>console.log('AI Job background worker listening'));
}
