#!/usr/bin/env python3
"""Enable ServGo same-origin owner Mail, preserving Growth and the legacy Mail host."""
import json
import os
from pathlib import Path
import subprocess
import time

DROPIN_DIR=Path("/etc/systemd/system/booking-web-api.service.d")
DROPIN=DROPIN_DIR/"99-servgo-mail-gateway.conf"
ENV_DIR=Path("/etc/servgo")
ENV_FILE=ENV_DIR/"mail-gateway.env"
TRUE={"1","true","yes","on"}

def run(args,timeout=30):
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if p.returncode:
        raise RuntimeError("Command failed: "+" ".join(args[:3])+": "+p.stderr[-200:])
    return p.stdout.strip()

def booking_env():
    pid=int(run(["systemctl","show","booking-web-api.service","--property=MainPID","--value"]))
    assert pid>1,"Booking API inactive"
    pairs=Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    return {k.decode():v.decode() for item in pairs if b"=" in item
            for k,v in [item.split(b"=",1)]}

def growth_env():
    data=json.loads(run(["docker","inspect","ai-growth-os-api-1"]))[0]
    assert data["State"]["Running"] and not data["State"]["Restarting"]
    return {k:v for entry in data["Config"]["Env"] if "=" in entry
            for k,v in [entry.split("=",1)]}

def curl(host,path,*,cookie=None,headers=False):
    args=["curl","-sS","--max-time","9","--resolve",f"{host}:443:127.0.0.1"]
    if cookie: args+=["-H","Cookie: "+cookie]
    if headers: args+=["-D","-","-o","/dev/null"]
    else: args+=["-o","/dev/null","-w","%{http_code}"]
    return run(args+[f"https://{host}{path}"],timeout=14)

def status(label,host,path,allowed):
    code=curl(host,path)
    print(f"{label}={code}",flush=True)
    assert code in allowed,label+" HTTP "+code

def smoke_common():
    status("SERVGO_API","servgo.ru","/api/health",{"200"})
    status("GROWTH_NEW_PROTECTED","servgo.ru","/studio",{"401","403"})
    status("GROWTH_OLD_PROTECTED","growth.servgo.ru","/studio",{"401","403"})
    status("MAIL_OLD_PROTECTED","mail.servgo.ru","/api/status",{"401","403"})
    status("PWA_MAIL_ENTRY","servgo.ru","/mail",{"200"})
    status("PWA_GROWTH_ENTRY","servgo.ru","/workspace/growth",{"200"})

def wait_api():
    for _ in range(25):
        try:
            if (run(["systemctl","is-active","booking-web-api.service"])=="active"
                and curl("servgo.ru","/api/health")=="200"):
                return
        except (RuntimeError,subprocess.TimeoutExpired):
            pass
        time.sleep(2)
    raise RuntimeError("Booking API restart health timeout")

def write_file(path,content,mode):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,mode)
    with os.fdopen(fd,"w") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())

def check_protected_mail():
    # Unauthenticated browsers may be directed to login; never return content.
    for route in ("/api/owner-mail/workspace",
                  "/api/owner-mail/workspace/mailbox"):
        result=curl("servgo.ru",route,headers=True).lower()
        first=result.splitlines()[0]
        assert " 303 " in first,route+" unprotected or inaccessible: "+first
        assert "\nlocation: /mail" in "\n"+result,route+" wrong login redirect"
        assert "cache-control: no-store" in result,route+" cache policy missing"
        assert "referrer-policy: no-referrer" in result,route+" referrer policy missing"
        print("MAIL_UNAUTH_REDIRECT_OK="+route,flush=True)
    forged=curl("servgo.ru","/api/owner-mail/workspace",cookie="servgo_owner_mail=not-a-jwt")
    assert forged=="303", "Forged mail cookie was not rejected"
    logout=curl("servgo.ru","/api/owner-mail/workspace/logout",headers=True).lower()
    assert " 303 " in logout.splitlines()[0]
    assert "\nlocation: /admin" in "\n"+logout
    assert "max-age=0" in logout and "path=/api/owner-mail" in logout
    print("MAIL_COOKIE_SCOPE_AND_LOGOUT=PASS",flush=True)

def main():
    assert os.geteuid()==0,"root required"
    assert not DROPIN.exists() and not ENV_FILE.exists(),"Mail gateway config already exists"
    assert Path("/etc/nginx/snippets/servgo-growth-gateway-20261101.conf").is_file()
    assert Path("/etc/systemd/system/booking-web-api.service.d/99-servgo-growth-issuer.conf").is_file()
    run(["nginx","-t"])
    before=booking_env()
    growth=growth_env()
    assert before.get("SERVGO_GROWTH_GATEWAY_ENABLED","").strip().lower() in TRUE,"Growth issuer not ready"
    assert growth.get("STUDIO_SERVGO_GATEWAY_ENABLED","").strip().lower() in TRUE,"Growth receiver not ready"
    assert before.get("SERVGO_MAIL_GATEWAY_ENABLED","").strip().lower() not in TRUE,"Mail already on"
    smoke_common()
    status("PRE_CANONICAL_MAIL_OFF","servgo.ru","/api/owner-mail/workspace",{"404"})
    print("MAIL_PREFLIGHT=PASS",flush=True)
    DROPIN_DIR.mkdir(parents=True,exist_ok=True)
    ENV_DIR.mkdir(mode=0o750,parents=True,exist_ok=True)
    try:
        write_file(ENV_FILE,"SERVGO_MAIL_GATEWAY_ENABLED=true\n",0o600)
        write_file(DROPIN,"[Service]\nEnvironmentFile="+str(ENV_FILE)+"\n",0o644)
        run(["systemctl","daemon-reload"])
        run(["systemctl","restart","booking-web-api.service"],timeout=90)
        wait_api()
        after=booking_env()
        assert after.get("SERVGO_MAIL_GATEWAY_ENABLED","").strip().lower() in TRUE,"Mail flag missing"
        assert after.get("SERVGO_GROWTH_GATEWAY_ENABLED","").strip().lower() in TRUE,"Growth issuer lost"
        assert after.get("STUDIO_SSO_SECRET")==before.get("STUDIO_SSO_SECRET"),"Growth SSO secret changed"
        smoke_common()
        check_protected_mail()
        print("MAIL_CANONICAL_ON_GROWTH_ON_LEGACY_PRESERVED=YES",flush=True)
        print("MAIL_ROLLBACK=remove Mail-only drop-in/env file, daemon-reload, restart Booking API",flush=True)
    except Exception:
        print("MAIL_GATEWAY_ROLLBACK_START",flush=True)
        DROPIN.unlink(missing_ok=True)
        ENV_FILE.unlink(missing_ok=True)
        run(["systemctl","daemon-reload"])
        run(["systemctl","restart","booking-web-api.service"],timeout=90)
        wait_api()
        restored=booking_env()
        assert restored.get("SERVGO_MAIL_GATEWAY_ENABLED","").strip().lower() not in TRUE
        assert restored.get("SERVGO_GROWTH_GATEWAY_ENABLED","").strip().lower() in TRUE
        smoke_common()
        status("MAIL_ROLLBACK_OFF","servgo.ru","/api/owner-mail/workspace",{"404"})
        print("MAIL_GATEWAY_ROLLBACK=PASS",flush=True)
        raise

if __name__=="__main__":
    main()
