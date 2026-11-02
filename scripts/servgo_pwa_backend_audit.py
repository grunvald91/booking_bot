"""Read-only server audit before harmonising Studio SSO and releasing PWA.
Never prints source, secrets, user data or file bodies.
"""
import ast
import difflib
import hashlib
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.deploy_business_creation_and_reminders import ROOT, connect, run
from scripts.servgo_unified_api_release import FILES

def digest(data):
    return hashlib.sha256(data).hexdigest()[:16] if data is not None else "missing"

def read(sftp, p):
    try:
        with sftp.open(p, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None

def nodes(data):
    parsed=ast.parse(data)
    def norm(n):
        return ast.dump(n, include_attributes=False)
    out={}
    for i,n in enumerate(parsed.body):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            key = n.name
        elif isinstance(n,ast.ImportFrom):
            key = "importfrom:"+str(n.module)+":"+str(n.level)
        elif isinstance(n,ast.Import):
            key = "import:"+",".join(a.name for a in n.names)
        elif isinstance(n,ast.Assign):
            key = "assign:"+",".join(t.id if isinstance(t,ast.Name) else type(t).__name__ for t in n.targets)
        elif isinstance(n,ast.AnnAssign):
            key = "annassign:"+(n.target.id if isinstance(n.target,ast.Name) else "other")
        else:
            key = type(n).__name__+":"+str(i)
        out.setdefault(key,[]).append(norm(n))
    return out

def ordered_nodes(data):
    out=[]
    for n in ast.parse(data).body:
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            key=type(n).__name__+":"+n.name
        elif isinstance(n,ast.ImportFrom):
            key="ImportFrom:"+str(n.module)
        elif isinstance(n,ast.Import):
            key="Import:"+",".join(a.name for a in n.names)
        elif isinstance(n,ast.Assign):
            key="Assign:"+",".join(t.id if isinstance(t,ast.Name) else type(t).__name__ for t in n.targets)
        else:
            key=type(n).__name__
        fingerprint=hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest()[:8]
        out.append(key+"@"+fingerprint)
    return out


def main():
    password = os.environ.get("SERVGO_PASSWORD")
    if not password:
        raise RuntimeError("SSH action secret missing")
    repo = Path(__file__).resolve().parents[1]
    client=connect(password)
    sftp=client.open_sftp()
    try:
        print("PWA_AUDIT service="+run(client,"systemctl is-active booking-web-api.service")+" nginx="+
              run(client,"systemctl is-active nginx")+" health="+
              run(client,"curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/health"),flush=True)
        for p in FILES:
            want=(repo/p).read_bytes()
            have=read(sftp,ROOT+"/"+p)
            print("PWA_AUDIT_BACKEND path="+p+" status="+("same" if have==want else "different")+
                  " remote="+digest(have)+" main="+digest(want),flush=True)
            if p.endswith("/studio_sso.py") and have is not None:
                remote, local = nodes(have), nodes(want)
                names=sorted(set(remote)|set(local))
                changed=[n for n in names if remote.get(n)!=local.get(n)]
                print("PWA_AUDIT_SSO changed_nodes="+str(changed)+" "+
                      "ast_equivalent="+str(not changed).lower()+
                      " server_nodes="+str(len(remote))+" main_nodes="+str(len(local)),flush=True)
                for name in changed:
                    print("PWA_AUDIT_SSO_NODE name="+name+
                          " server_present="+str(name in remote).lower()+
                          " main_present="+str(name in local).lower(),flush=True)
                left,right=ordered_nodes(have),ordered_nodes(want)
                print("PWA_AUDIT_SSO_MODULE_MATCH="+str(
                    ast.dump(ast.parse(have),include_attributes=False)==
                    ast.dump(ast.parse(want),include_attributes=False)).lower(),flush=True)
                diffs=[(tag,a,b,c,d) for tag,a,b,c,d in
                       difflib.SequenceMatcher(a=left,b=right,autojunk=False).get_opcodes()
                       if tag!="equal"]
                for tag,a,b,c,d in diffs:
                    print("PWA_AUDIT_SSO_ORDER_OP tag="+tag+
                          " live_range="+str((a,b))+" main_range="+str((c,d))+
                          " live="+str(left[a:b])+" main="+str(right[c:d]),flush=True)
        front=ROOT+"/web/frontend"
        actual=run(client,"readlink "+front+"/dist || true")
        print("PWA_AUDIT_FRONTEND current_link="+("release" if actual.startswith("releases/") else "other")+
              " sw_main_version="+str(b"servgo-pwa-v4" in (repo/"web/frontend/public/sw.js").read_bytes()).lower(),flush=True)
        print("PWA_AUDIT_DONE production_untouched=true",flush=True)
    finally:
        sftp.close()
        client.close()

if __name__ == "__main__":
    main()
