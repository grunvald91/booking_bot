#!/usr/bin/env python3
"""Growth receiver only: guarded same-origin opt-in. Booking issuer and Mail stay OFF."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

API = "ai-growth-os-api-1"
OVERLAY = Path("/opt/ai_growth_os/deploy/servgo-growth-receiver-stage2.json")
ROLLBACK = Path("/opt/ai_growth_os/deploy/servgo-growth-receiver-stage2-rollback.json")
PROJECT = ["docker", "compose", "--project-name", "ai-growth-os",
           "--env-file", "/opt/ai_growth_os/.env"]
TRUE = {"1", "true", "yes", "on"}

def run(args, cwd=None, timeout=30):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError("Failed: " + " ".join(args[:3]) + ": " + p.stderr[-200:])
    return p.stdout.strip()

def vars_from(items):
    return dict(line.split("=", 1) for line in items if "=" in line)

def growth():
    info = json.loads(run(["docker", "inspect", API]))[0]
    assert info["State"]["Running"] and not info["State"]["Restarting"], "Growth unhealthy"
    return info, vars_from(info["Config"]["Env"])

def booking():
    pid = int(run(["systemctl", "show", "booking-web-api.service",
                   "--property=MainPID", "--value"]))
    assert pid > 1, "Booking API inactive"
    entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    return {k.decode(): v.decode() for item in entries if b"=" in item
            for k, v in [item.split(b"=", 1)]}

def check_http(label, host, path, allowed):
    code = run(["curl", "-sS", "--max-time", "9", "--resolve",
                f"{host}:443:127.0.0.1", "-o", "/dev/null",
                "-w", "%{http_code}", f"https://{host}{path}"], timeout=14)
    print(f"{label}={code}", flush=True)
    assert code in allowed, f"{label} unexpected HTTP {code}"

def checks():
    check_http("API", "servgo.ru", "/api/health", {"200"})
    check_http("GROWTH_LEGACY", "growth.servgo.ru", "/studio", {"401", "403"})
    check_http("MAIL_LEGACY", "mail.servgo.ru", "/api/status", {"401", "403"})
    check_http("CANONICAL_GROWTH_GUARDED", "servgo.ru", "/studio", {"401", "403"})
    check_http("CANONICAL_BAD_SSO_TICKET", "servgo.ru", "/studio/sso?t=bad", {"400"})
    check_http("CANONICAL_MAIL_OFF", "servgo.ru", "/api/owner-mail/workspace", {"404"})

def compose(files, cwd, *args):
    run(PROJECT + [part for f in files for part in ("-f", f)] + list(args),
        cwd=cwd, timeout=100)

def health():
    for _ in range(25):
        try:
            if run(["curl", "-sS", "--max-time", "3", "-o", "/dev/null",
                    "-w", "%{http_code}", "http://127.0.0.1:8091/health"],
                   timeout=6) == "200":
                return
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        time.sleep(2)
    raise RuntimeError("Growth failed health after restart")

def csrf_contract():
    code = r"""
from starlette.requests import Request
from fastapi import HTTPException
from app.core.config import get_settings
from app.api.content_studio_auth import require_studio_csrf
settings=get_settings()
assert settings.studio_servgo_gateway_enabled is True
assert str(settings.studio_public_origin)=='https://growth.servgo.ru'
def request(host, origin):
    return Request({'type':'http','method':'POST','scheme':'https',
        'server':(host,443),'path':'/studio/products/test/create',
        'headers':[(b'host',host.encode()),(b'origin',origin.encode())],
        'query_string':b''})
assert require_studio_csrf(request('servgo.ru','https://servgo.ru'),settings=settings) is None
assert require_studio_csrf(request('growth.servgo.ru','https://growth.servgo.ru'),settings=settings) is None
for host,origin in [('growth.servgo.ru','https://servgo.ru'),
                    ('servgo.ru','https://growth.servgo.ru')]:
    try: require_studio_csrf(request(host,origin),settings=settings)
    except HTTPException as err: assert err.status_code==403
    else: raise AssertionError('Cross-origin access was accepted')
print('GROWTH_CSRF_ORIGIN_GUARD=PASS')
"""
    result = run(["docker", "exec", API, "python", "-c", code], timeout=40)
    assert "GROWTH_CSRF_ORIGIN_GUARD=PASS" in result
    print("GROWTH_CSRF_ORIGIN_GUARD=PASS", flush=True)

def main():
    assert os.geteuid()==0, "root required"
    assert not OVERLAY.exists() and not ROLLBACK.exists(), "Existing stage2 state; refuse reapply"
    assert Path("/etc/nginx/snippets/servgo-growth-gateway-20261101.conf").is_file()
    run(["nginx", "-t"])
    b=booking()
    for flag in ("SERVGO_GROWTH_GATEWAY_ENABLED","SERVGO_MAIL_GATEWAY_ENABLED"):
        assert b.get(flag,"").lower() not in TRUE, flag + " unexpectedly enabled"
    info,env=growth()
    assert env.get("STUDIO_SERVGO_GATEWAY_ENABLED","").lower() not in TRUE
    assert env.get("STUDIO_PUBLIC_ORIGIN")=="https://growth.servgo.ru"
    for booking_key,growth_key in (("STUDIO_SSO_SECRET","SERVGO_SSO_SECRET"),
                                   ("STUDIO_INTERNAL_KEY","SERVGO_INTERNAL_KEY")):
        assert len(b.get(booking_key,""))>=32 and b[booking_key]==env.get(growth_key), "SSO pair mismatch"
    labels=info["Config"]["Labels"]
    assert labels["com.docker.compose.project"]=="ai-growth-os"
    files=labels["com.docker.compose.project.config_files"].split(",")
    cwd=labels["com.docker.compose.project.working_dir"]
    assert all(Path(f).is_file() for f in files) and Path(cwd).is_dir()
    spec=importlib.util.spec_from_file_location("growth_deploy","/opt/ai_growth_os/deploy/deploy_growth.py")
    assert spec and spec.loader
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.busy_jobs()==0, "Growth agent tasks active; refuse restart"
    checks()
    print("GROWTH_RECEIVER_PREFLIGHT=PASS", flush=True)
    def exclusive_write(path,data):
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w") as fp:
            json.dump(data,fp,indent=2)
            fp.write("\n")
            fp.flush()
            os.fsync(fp.fileno())
    exclusive_write(ROLLBACK, {"files":files,"cwd":cwd})
    exclusive_write(OVERLAY, {"services":{"api":{"environment":{"STUDIO_SERVGO_GATEWAY_ENABLED":"true"}}}})
    touched=False
    try:
        updated=files+[str(OVERLAY)]
        compose(updated,cwd,"config","--quiet")
        touched=True
        compose(updated,cwd,"up","-d","--no-deps","--no-build","api")
        health()
        _,after=growth()
        assert after.get("STUDIO_SERVGO_GATEWAY_ENABLED","").lower() in TRUE
        assert booking().get("SERVGO_GROWTH_GATEWAY_ENABLED","").lower() not in TRUE
        assert booking().get("SERVGO_MAIL_GATEWAY_ENABLED","").lower() not in TRUE
        csrf_contract()
        checks()
        print("GROWTH_RECEIVER_ON_ISSUER_OFF_MAIL_OFF=YES", flush=True)
        print("GROWTH_ROLLBACK_MANIFEST="+str(ROLLBACK),flush=True)
    except Exception:
        if touched:
            print("GROWTH_RECEIVER_ROLLBACK_START",flush=True)
            compose(files,cwd,"up","-d","--no-deps","--no-build","api")
            health()
            _,restored=growth()
            assert restored.get("STUDIO_SERVGO_GATEWAY_ENABLED","").lower() not in TRUE
        OVERLAY.unlink(missing_ok=True)
        ROLLBACK.unlink(missing_ok=True)
        print("GROWTH_RECEIVER_ROLLBACK=PASS",flush=True)
        raise

if __name__=="__main__":
    main()
