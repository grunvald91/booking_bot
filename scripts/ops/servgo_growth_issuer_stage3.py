#!/usr/bin/env python3
"""Activate BookingBot Growth SSO issuer only. Preserve Mail and both legacy hosts."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

DROPIN_DIR = Path("/etc/systemd/system/booking-web-api.service.d")
DROPIN = DROPIN_DIR / "99-servgo-growth-issuer.conf"
ENV_DIR = Path("/etc/servgo")
ENV_FILE = ENV_DIR / "growth-issuer.env"
GROWTH = "ai-growth-os-api-1"
TRUE = {"1", "true", "yes", "on"}

def run(args, timeout=30):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Command failed: " + " ".join(args[:3]) + ": " + result.stderr[-200:])
    return result.stdout.strip()

def env_pairs(entries):
    return {key: value for entry in entries if "=" in entry
            for key, value in [entry.split("=", 1)]}

def booking_env():
    pid = int(run(["systemctl", "show", "booking-web-api.service",
                   "--property=MainPID", "--value"]))
    assert pid > 1, "Booking API not running"
    entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    return {key.decode(): value.decode() for item in entries if b"=" in item
            for key, value in [item.split(b"=", 1)]}

def growth_env():
    record = json.loads(run(["docker", "inspect", GROWTH]))[0]
    assert record["State"]["Running"] and not record["State"]["Restarting"]
    return env_pairs(record["Config"]["Env"])

def curl(host, path):
    return run(["curl", "-sS", "--max-time", "9", "--resolve",
                f"{host}:443:127.0.0.1", "-o", "/dev/null",
                "-w", "%{http_code}", f"https://{host}{path}"], timeout=14)

def probe(label, host, path, statuses):
    result = curl(host, path)
    print(f"{label}={result}", flush=True)
    assert result in statuses, f"Unexpected {label}: {result}"

def smoke():
    probe("BOOKING_API", "servgo.ru", "/api/health", {"200"})
    probe("CANONICAL_GROWTH_PROTECTED", "servgo.ru", "/studio", {"401", "403"})
    probe("LEGACY_GROWTH_PROTECTED", "growth.servgo.ru", "/studio", {"401", "403"})
    probe("LEGACY_MAIL_PROTECTED", "mail.servgo.ru", "/api/status", {"401", "403"})
    probe("CANONICAL_MAIL_OFF", "servgo.ru", "/api/owner-mail/workspace", {"404"})
    probe("GROWTH_WORKSPACE_ENTRY", "servgo.ru", "/workspace/growth", {"200"})

def health():
    for _ in range(25):
        try:
            if run(["systemctl", "is-active", "booking-web-api.service"]) == "active":
                if curl("servgo.ru", "/api/health") == "200":
                    return
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        time.sleep(2)
    raise RuntimeError("Booking API failed health after restart")

def exclusive_write(path, content, mode):
    descriptor = os.open(path, os.O_CREAT|os.O_EXCL|os.O_WRONLY, mode)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())

def signed_forbidden_ticket(secret):
    claims = {"v":1, "aud":"growth-studio", "uid":0, "biz":0,
              "role":"owner", "name":"guarded-probe",
              "jti":secrets.token_urlsafe(16), "exp":int(time.time())+45}
    payload = base64.urlsafe_b64encode(
        json.dumps(claims, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return payload + "." + signature

def main():
    assert os.geteuid()==0, "root required"
    assert not DROPIN.exists() and not ENV_FILE.exists(), "Issuer files already exist"
    assert Path("/etc/nginx/snippets/servgo-growth-gateway-20261101.conf").is_file()
    run(["nginx", "-t"])
    b=booking_env()
    g=growth_env()
    assert b.get("SERVGO_GROWTH_GATEWAY_ENABLED", "").strip().lower() not in TRUE, "Issuer already enabled"
    assert b.get("SERVGO_MAIL_GATEWAY_ENABLED", "").strip().lower() not in TRUE, "Mail must remain OFF"
    assert g.get("STUDIO_SERVGO_GATEWAY_ENABLED", "").strip().lower() in TRUE, "Growth receiver not ready"
    assert g.get("STUDIO_PUBLIC_ORIGIN")=="https://growth.servgo.ru"
    for booking_key,growth_key in (("STUDIO_SSO_SECRET","SERVGO_SSO_SECRET"),
                                   ("STUDIO_INTERNAL_KEY","SERVGO_INTERNAL_KEY")):
        assert len(b.get(booking_key,""))>=32 and b[booking_key]==g.get(growth_key), "SSO secrets mismatched"
    smoke()
    # Confirm existing public app handles a signed but unauthorized user without granting a session.
    # No owner identity is impersonated and no SSO ticket is exposed in logs.
    invalid = signed_forbidden_ticket(b["STUDIO_SSO_SECRET"])
    probe("CANONICAL_SSO_UNAUTHORIZED", "servgo.ru", "/studio/sso?t="+invalid, {"403"})
    DROPIN_DIR.mkdir(parents=True, exist_ok=True)
    ENV_DIR.mkdir(mode=0o750, parents=True, exist_ok=True)
    print("GROWTH_ISSUER_PREFLIGHT=PASS", flush=True)
    touched=False
    try:
        exclusive_write(ENV_FILE, "SERVGO_GROWTH_GATEWAY_ENABLED=true\n", 0o600)
        exclusive_write(DROPIN, "[Service]\nEnvironmentFile="+str(ENV_FILE)+"\n", 0o644)
        touched=True
        run(["systemctl","daemon-reload"])
        run(["systemctl","restart","booking-web-api.service"],timeout=90)
        health()
        b2=booking_env()
        assert b2.get("SERVGO_GROWTH_GATEWAY_ENABLED","").strip().lower() in TRUE, "Flag not applied"
        assert b2.get("SERVGO_MAIL_GATEWAY_ENABLED","").strip().lower() not in TRUE, "Mail unexpectedly enabled"
        assert b2.get("STUDIO_SSO_SECRET")==b["STUDIO_SSO_SECRET"], "SSO secret changed"
        smoke()
        probe("CANONICAL_SSO_UNAUTHORIZED", "servgo.ru", "/studio/sso?t="+invalid, {"403"})
        print("GROWTH_ISSUER_ON_MAIL_OFF=YES",flush=True)
        print("ISSUER_ROLLBACK=remove dedicated systemd drop-in and env-file; daemon-reload; restart API",flush=True)
    except Exception:
        print("GROWTH_ISSUER_ROLLBACK_START",flush=True)
        if touched or DROPIN.exists() or ENV_FILE.exists():
            DROPIN.unlink(missing_ok=True)
            ENV_FILE.unlink(missing_ok=True)
            run(["systemctl","daemon-reload"])
            run(["systemctl","restart","booking-web-api.service"],timeout=90)
            health()
            assert booking_env().get("SERVGO_GROWTH_GATEWAY_ENABLED","").strip().lower() not in TRUE
            smoke()
        print("GROWTH_ISSUER_ROLLBACK=PASS",flush=True)
        raise

if __name__=="__main__":
    main()
