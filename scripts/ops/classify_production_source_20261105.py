#!/usr/bin/env python3
"""Read-only classification of the seven production-only/differing source files.

Never exports file contents; filtered diff excerpts contain no credential-like
values. No changes to GitHub main or production.
"""
from __future__ import annotations
import base64
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import paramiko

HOST="155.212.162.47"
FINGERPRINT="uQJp3lT4golKb3lsDTCFozGWR1ihlu1w/Oa4cSzCdpU"
ROOT="/opt/booking_bot/"
MAIN="f1529d1bf4960b5e0ad282f05eb9f651faf1cb36"
DIFF=[
"web/api/routes/studio_sso.py",
"web/api/schemas.py",
"web/frontend/package-lock.json",
"web/frontend/src/components/AdminShell.tsx",
"web/frontend/src/components/Layout.tsx",
"web/frontend/src/components/OwnerMailEntry.tsx",
]
EXTRA="webapp/promo_standalone.py"
def sha(b):return hashlib.sha256(b).hexdigest()
def git(*args):return subprocess.run(["git",*args],capture_output=True,check=True).stdout
class Pinned(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self,client,hostname,key):
        actual=base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        if actual!=FINGERPRINT:raise RuntimeError("SSH host fingerprint mismatch")
        client.get_host_keys().add(hostname,key.get_name(),key)
def remote():
    for attempt in range(3):
        ssh=paramiko.SSHClient();ssh.set_missing_host_key_policy(Pinned())
        try:
            ssh.connect(HOST,username="root",password=os.environ["SERVER_PASSWORD"],port=22,
                look_for_keys=False,allow_agent=False,timeout=12,banner_timeout=25,auth_timeout=15)
            return ssh
        except (paramiko.SSHException,OSError,EOFError):
            ssh.close()
            if attempt==2:raise
            time.sleep(2)
def clean(line):
    # No raw secret-looking assignments, URLs containing credentials or API keys.
    if re.search(r"(?i)(password|passwd|secret|token|api[_-]?key|credential|PRIVATE KEY|postgres(?:ql)?://).{0,80}[:=]",line):
        return "<redacted potentially sensitive source line>"
    line=re.sub(r"(?i)\b(?:ghp_|github_pat_|sk-[\w-]{8,}|AKIA)[\w-]+","<redacted>",line)
    return line[:190].rstrip()
def diff_excerpt(path,local,live):
    try:
        a=local.decode("utf-8").splitlines();b=live.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        print("DIFF",path,"binary_or_non_utf8")
        return
    lines=list(difflib.unified_diff(a,b,fromfile="main/"+path,tofile="production/"+path,n=1))
    markers=[line for line in lines if line.startswith("@@")]
    print("HUNKS",path,"hunks="+str(len(markers)),"line_count_delta="+str(len(b)-len(a)))
    if path.endswith("package-lock.json"):
        try:
            x=json.loads(local);y=json.loads(live)
            na=x.get("packages",{});nb=y.get("packages",{})
            changed=[k for k in set(na)|set(nb) if (na.get(k) or {}).get("version") != (nb.get(k) or {}).get("version")]
            print("PACKAGE_LOCK_VERSION_CHANGED_COUNT",len(changed))
            for name in sorted(changed)[:45]:
                print("PACKAGE_VERSION",clean(name),
                      "main="+clean(str((na.get(name) or {}).get("version","-"))),
                      "server="+clean(str((nb.get(name) or {}).get("version","-"))))
        except Exception as e:
            print("PACKAGE_LOCK_PARSE",type(e).__name__)
    else:
        for line in lines[:170]:
            print("PATCH",path,clean(line))
        if len(lines)>170:print("PATCH_TRUNCATED",path,len(lines)-170)

current=git("rev-parse","HEAD").decode().strip()
assert current==MAIN,(current,MAIN)
print("CLASSIFY_SOURCE_MAIN",MAIN)
ssh=remote()
try:
    sftp=ssh.open_sftp()
    for path in DIFF+[EXTRA]:
        try:
            with sftp.open(ROOT+path,"rb") as stream: live=stream.read()
        except FileNotFoundError:
            print("SERVER_MISSING",path)
            continue
        local=Path(path).read_bytes() if Path(path).exists() else None
        print("SOURCE_FILE",path,"server_sha256="+sha(live),"bytes="+str(len(live)),
             "main_sha256="+(sha(local) if local is not None else "NOT_TRACKED"))
        if local is not None and sha(local)==sha(live):
            print("CLASS",path,"IDENTICAL")
            continue
        if path=="web/api/routes/studio_sso.py" and local is not None:
            import ast
            def func(node):
                return node.name if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) else None
            raw_nodes=ast.parse(live.decode("utf-8")).body
            main_nodes=ast.parse(local.decode("utf-8")).body
            moved=("_businesses_for_studio","studio_accessible_businesses")
            canonical=lambda node:ast.dump(node,include_attributes=False)
            server_moved=list(raw_nodes[-2:])
            target_moved=[next((node for node in main_nodes if func(node)==name),None) for name in moved]
            same_moved=all(target_moved) and [canonical(node) for node in server_moved]==[canonical(node) for node in target_moved]
            base_nodes=[node for node in main_nodes if func(node) not in moved]
            server_other=raw_nodes[:-2]
            same_rest=[canonical(node) for node in server_other]==[canonical(node) for node in base_nodes]
            print("STUDIO_SSO_AST_EQUIVALENT",bool(
                [func(node) for node in server_moved]==list(moved) and same_moved and same_rest))
        if local is not None:
            # Identify production files which are exact older versions from history.
            versions=git("log","--format=%H","--",path).decode().split()
            older=[]
            for commit in versions[:75]:
                p=subprocess.run(["git","show",commit+":"+path],capture_output=True)
                if p.returncode==0 and sha(p.stdout)==sha(live):
                    older.append(commit)
                    break
            print("CLASS",path,"HISTORICAL_REVISION" if older else "UNIQUE_SERVER_VERSION",
                  "historical_commit="+(older[0] if older else "none"))
            diff_excerpt(path,local,live)
        else:
            # Don't reveal server-only file content, but inspect import and syntax characteristics.
            text=live.decode("utf8",errors="replace")
            print("SERVER_ONLY_FILE",path,"lines="+str(len(text.splitlines())),
                  "imports="+str(sum(1 for x in text.splitlines() if re.match(r"^(from|import)\s+",x))),
                  "defines="+str(sum(1 for x in text.splitlines() if re.match(r"^(async\s+def|def|class)\s+",x))))
            print("SERVER_ONLY_NAMES",path,[x for x in re.findall(r"^(?:async\s+)?def\s+([a-zA-Z_]\w*)\s*\(",text,re.M) if not any(v in x.lower() for v in ("key","secret","token","password"))][:22])
    # Detect whether the untracked server-only promo entrypoint is referenced
    # by running processes or service configs. Report only booleans and counts.
    remote_code="""import os, pathlib
needle=b'promo_standalone'
pids=0
for pid in pathlib.Path('/proc').iterdir():
    if not pid.name.isdigit():continue
    try:
        if needle in (pid/'cmdline').read_bytes():pids+=1
    except (OSError,PermissionError):pass
print('PROMO_SERVER_ACTIVE_PROCESSES',pids)
for root in ('/etc/systemd/system','/etc/nginx'):
    count=0
    for base,dirs,files in os.walk(root):
        dirs[:]=[name for name in dirs if name not in ('.git','private','secrets')]
        for name in files:
            path=pathlib.Path(base)/name
            if not (path.is_file() and path.stat().st_size<300000):continue
            try:
                if needle in path.read_bytes():count+=1
            except (OSError,PermissionError):pass
    print('PROMO_CONFIG_REFERENCES',root,count)
"""
    import base64 as b64
    import shlex
    cmd="python3 -c "+shlex.quote("import base64;exec(base64.b64decode("+repr(b64.b64encode(remote_code.encode()).decode())+"))")
    _,stdout,stderr=ssh.exec_command(cmd,timeout=30)
    stdout.channel.settimeout(35)
    print(stdout.read(2048).decode("utf8",errors="replace").strip())
    sftp.close()
finally:
    ssh.close()
print("CLASSIFICATION_READ_ONLY_COMPLETE")
