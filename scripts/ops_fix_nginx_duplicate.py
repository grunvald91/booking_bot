#!/usr/bin/env python3
"""Conservative one-off repair for a duplicate ServGo nginx vhost.

Expected to run as root on the already pinned ServGo SSH host.
Never prints nginx config bodies, secrets, environment values or response data.
Apply is permitted only when *all* safety assertions hold.
"""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time

PRIMARY = Path("/etc/nginx/sites-enabled/webapp")
DUPLICATE = Path("/etc/nginx/sites-enabled/webapp.bak_auth3_")
DISABLED = Path("/etc/nginx/disabled-site-backups")
EXPECTED_CONFIG_SHA256 = "d0973ed14aec6e5f73ad6f360d86a318a4bf8f2633fced38e7fc73f92aa34964"
WARNING_MARKER = "conflicting server name"
SMOKE = [
    ("servgo.ru", "/"),
    ("servgo.ru", "/sw.js"),
    ("servgo.ru", "/manifest.webmanifest"),
    ("servgo.ru", "/api/health"),
    ("growth.servgo.ru", "/studio"),
    ("mail.servgo.ru", "/"),
]


def call(argv, timeout=30):
    return subprocess.run(
        argv, capture_output=True, text=True, check=False, timeout=timeout
    )


def digest(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def block_body(text, pos):
    level = 1
    quote = None
    escape = False
    for i in range(pos, len(text)):
        char = text[i]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char in "'\"":
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            continue
        if quote is not None:
            continue
        if char == "{":
            level += 1
        elif char == "}":
            level -= 1
            if level == 0:
                return text[pos:i]
    raise RuntimeError("unterminated nginx server block")


def nginx_details():
    p = call(["nginx", "-T"], timeout=30)
    if p.returncode:
        raise RuntimeError("nginx -T failed, no change allowed")
    warnings = [s.strip() for s in p.stderr.splitlines()
                if WARNING_MARKER in s]
    return p.stdout, warnings


def parse_servers(raw):
    markers = list(re.finditer(r"(?m)^# configuration file ([^\n:]+):", raw))
    if not markers:
        raise RuntimeError("nginx -T lacks source file markers")
    entries = []
    for match in re.finditer(r"(?m)^\s*server\s*\{", raw):
        body = block_body(raw, match.end())
        previous = [m.group(1) for m in markers if m.start() <= match.start()]
        if not previous:
            continue
        path = previous[-1]
        names = []
        for value in re.findall(r"(?m)^\s*server_name\s+([^;]+);", body):
            names.extend(value.strip().split())
        listens = re.findall(r"(?m)^\s*listen\s+([^;]+);", body)
        listens = [s.strip() for s in listens]
        entries.append({
            "file": path,
            "names": set(names),
            "listen": set(listens),
            "has_default": any("default_server" in s for s in listens),
            "has_sw": bool(re.search(
                r"(?m)^\s*location\s+=\s*/sw\.js\s*\{", body
            )),
        })
    return entries


def normalize_listener(listener):
    parts = listener.split()
    if not parts:
        return "unknown"
    address = parts[0].lower()
    if address in ("443", "80"):
        return "ipv4:" + address
    if address in ("[::]:443", "[::]:80"):
        return "ipv6:" + address.split(":")[-1]
    if address.startswith("0.0.0.0:"):
        return "ipv4:" + address.split(":")[-1]
    return address


def cover(servers):
    # Set of (domain name, listener family and port) for active server blocks.
    return {(name, normalize_listener(listener))
            for block in servers
            for name in block["names"]
            for listener in block["listen"]}


def smoke(host, path):
    p = call([
        "curl", "--noproxy", "*", "--silent", "--show-error",
        "--max-time", "9", "--resolve", f"{host}:443:127.0.0.1",
        "--output", "/dev/null", "--write-out", "%{http_code}",
        f"https://{host}{path}",
    ], timeout=12)
    status = p.stdout.strip()
    if p.returncode != 0 or not re.fullmatch(r"[1-5]\d\d", status):
        raise RuntimeError("HTTPS smoke unavailable for " + host + path)
    return int(status)


def smoke_all():
    result = {}
    for host, path in SMOKE:
        result[host + path] = smoke(host, path)
    return result


def must_pass_nginx():
    result = call(["nginx", "-t"], timeout=25)
    if result.returncode:
        raise RuntimeError("nginx -t failed")
    return [line for line in result.stderr.splitlines()
            if WARNING_MARKER in line]


def reload_nginx():
    result = call(["systemctl", "reload", "nginx"], timeout=30)
    if result.returncode:
        raise RuntimeError("systemctl reload nginx failed")
    check = call(["systemctl", "is-active", "nginx"], timeout=10)
    if check.returncode or check.stdout.strip() != "active":
        raise RuntimeError("nginx not active after reload")


def rollback(moved_to, did_reload):
    if not moved_to or not moved_to.exists():
        print("rollback_required=no", flush=True)
        return
    if DUPLICATE.exists() or DUPLICATE.is_symlink():
        raise RuntimeError("rollback path already occupied; manual intervention required")
    os.rename(moved_to, DUPLICATE)
    must_pass_nginx()
    if did_reload:
        reload_nginx()
        result = smoke_all()
        print("rollback_https_checks=" + str(len(result)), flush=True)
    print("rollback_restored=yes", flush=True)


def main():
    print("operation=nginx_duplicate_vhost_repair")
    print("mode=conservative_apply_with_automatic_rollback")
    print("target=" + str(DUPLICATE))
    print("production_code_changes=no")
    print("expected_nginx_sha256=" + EXPECTED_CONFIG_SHA256)

    if os.geteuid() != 0:
        raise RuntimeError("root needed for atomic nginx config repair")
    if not (PRIMARY.exists() and (DUPLICATE.exists() or DUPLICATE.is_symlink())):
        raise RuntimeError("expected primary or duplicate config missing")
    if not PRIMARY.is_file() or not DUPLICATE.is_file():
        raise RuntimeError("nginx config is not a normal readable file")
    if not str(DUPLICATE).startswith("/etc/nginx/sites-enabled/"):
        raise RuntimeError("unsafe file path")
    if not all(t not in DUPLICATE.name for t in ("../", "/")):
        raise RuntimeError("unsafe file name")

    raw, warnings_before = nginx_details()
    current_digest = digest(raw)
    print("nginx_preflight_sha256=" + current_digest)
    if current_digest != EXPECTED_CONFIG_SHA256:
        raise RuntimeError("nginx config drifted since approved audit")
    must_pass_nginx()

    entries = parse_servers(raw)
    primary = [b for b in entries if b["file"] == str(PRIMARY)]
    duplicate = [b for b in entries if b["file"] == str(DUPLICATE)]
    if not primary or not duplicate:
        raise RuntimeError("expected vhost not loaded under observed source names")

    print("primary_server_blocks=" + str(len(primary)))
    print("duplicate_server_blocks=" + str(len(duplicate)))
    print("primary_hostnames=" + ",".join(sorted(set().union(*(b["names"] for b in primary)))))
    print("duplicate_hostnames=" + ",".join(sorted(set().union(*(b["names"] for b in duplicate)))))
    print("warnings_before_count=" + str(len(warnings_before)))
    servgo_warning_before = sum(
        "servgo.ru" in w and ":443" in w for w in warnings_before
    )
    if servgo_warning_before == 0:
        raise RuntimeError("expected servgo.ru:443 duplicate warning absent")

    # No wildcard/default/regex/variable vhosts may be removed as a side effect.
    for b in duplicate:
        if b["has_default"] or not b["names"] or not b["listen"]:
            raise RuntimeError("backup contains a default or unnamed server")
        if any(not re.fullmatch(r"[a-z0-9.-]+", host) for host in b["names"]):
            raise RuntimeError("backup contains wildcard or regex server_name")
    other = [b for b in entries if b["file"] != str(DUPLICATE)]
    uncovered = cover(duplicate) - cover(other)
    if uncovered:
        # Only the missing names and ports, no nginx private directives.
        print("uncovered_hostname_listener_count=" + str(len(uncovered)))
        raise RuntimeError("duplicate backup has unique live host bindings; aborting")

    primary_covers_servgo = (
        ("servgo.ru", "ipv4:443") in cover(primary)
        and any(b["has_sw"] for b in primary)
    )
    if not primary_covers_servgo:
        raise RuntimeError("primary vhost does not cover ServGo HTTPS + /sw.js")
    print("all_backup_hosts_covered_elsewhere=yes")

    baseline = smoke_all()
    print("baseline_status=" + ",".join(
        key + ":" + str(value) for key, value in baseline.items()
    ))
    if any(baseline[host + path] >= 500 for host, path in SMOKE):
        raise RuntimeError("some baseline endpoints unhealthy, refusing reload")
    if baseline.get("servgo.ru/sw.js", 0) not in (200, 304):
        raise RuntimeError("primary PWA service worker unavailable")
    if baseline.get("servgo.ru/", 0) not in (200, 301, 302, 307, 308):
        raise RuntimeError("main ServGo landing page unhealthy")

    source_sha = hashlib.sha256(DUPLICATE.read_bytes()).hexdigest()
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    destination = DISABLED / (DUPLICATE.name + "." + timestamp)
    if destination.exists():
        raise RuntimeError("destination collision")
    DISABLED.mkdir(mode=0o700, parents=True, exist_ok=True)
    DISABLED.chmod(0o700)

    moved = False
    did_reload = False
    try:
        os.rename(DUPLICATE, destination)
        moved = True
        if not destination.is_file() or hashlib.sha256(
            destination.read_bytes()
        ).hexdigest() != source_sha:
            raise RuntimeError("moved backup hash mismatch")

        warnings_after = must_pass_nginx()
        if len(warnings_after) > len(warnings_before):
            raise RuntimeError("nginx warning count increased")
        if any("servgo.ru" in w and ":443" in w for w in warnings_after):
            raise RuntimeError("duplicate servgo.ru HTTPS warning still present")
        # Recheck that nginx -T parses correctly without source backup.
        new_raw, _ = nginx_details()
        new_entries = parse_servers(new_raw)
        if any(b["file"] == str(DUPLICATE) for b in new_entries):
            raise RuntimeError("disabled backup still included by nginx")
        if ("servgo.ru", "ipv4:443") not in cover(new_entries):
            raise RuntimeError("primary servgo.ru HTTPS vhost disappeared")

        # Treat the reload as potentially applied even if systemctl returns an
        # unexpected failure; rollback must issue its own reload in that case.
        did_reload = True
        reload_nginx()
        time.sleep(1)
        after = smoke_all()
        print("post_reload_status=" + ",".join(
            key + ":" + str(value) for key, value in after.items()
        ))
        if baseline != after:
            raise RuntimeError("HTTP status changed after nginx reload")
        print("warnings_after_count=" + str(len(warnings_after)))
        print("backup_preserved=" + str(destination))
        print("backup_sha256=" + source_sha)
        print("nginx_active=yes")
        print("rollback_needed=no")
        print("repair_result=success", flush=True)
        return 0
    except BaseException as exc:
        print("repair_error_type=" + type(exc).__name__)
        print("repair_error=" + str(exc)[:160])
        try:
            rollback(destination if moved else None, did_reload)
        except BaseException as restoration_error:
            print("rollback_error_type=" + type(restoration_error).__name__)
            print("rollback_manual_attention_needed=yes")
        print("repair_result=failed", flush=True)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaseException as exc:
        print("preflight_error_type=" + type(exc).__name__)
        print("preflight_error=" + str(exc)[:160])
        print("repair_result=not_applied", flush=True)
        sys.exit(1)
