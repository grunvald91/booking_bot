#!/usr/bin/env python3
"""Guarded nginx rollout for Google-readable company blogs on servgo.ru.

Execute on production via verified SSH: python3 - <mode>
Modes: inspect (read only), apply (backup, validate, reload, smoke, rollback).
No system configuration except /etc/nginx/sites-enabled/webapp is changed.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

SITE = Path("/etc/nginx/sites-enabled/webapp")
BACKUPS = Path("/opt/booking_bot/backups/company-seo-nginx")
MARK = "# SERVGO_COMPANY_SEO_SSR_BEGIN"
SNIPPET = """
    # SERVGO_COMPANY_SEO_SSR_BEGIN
    # Public company SEO must never fall through to the shared React shell.
    location ~ ^/business/([0-9]+)/blog/$ {
        return 301 /business/$1/blog$is_args$args;
    }
    location ~ ^/business/([0-9]+)/blog/(.+)/$ {
        return 301 /business/$1/blog/$2$is_args$args;
    }
    location ~ ^/business/([0-9]+)/blog(?:/|$) {
        limit_except GET HEAD { deny all; }
        rewrite ^/business/([0-9]+)/blog(.*)$ /api/seo-pages/business/$1/blog$2 last;
    }
    # SERVGO_COMPANY_SEO_SSR_END

"""
ANCHOR = "    location = /blog { proxy_pass http://127.0.0.1:8080;"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=25)


def request(path: str) -> tuple[int, str, str]:
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("Untrusted route")
    cp = run("curl", "-ksS", "--max-time", "12", "--resolve",
             "servgo.ru:443:127.0.0.1", "-w",
             "\\n__STATUS__=%{http_code}:%{content_type}",
             "https://servgo.ru" + path)
    if cp.returncode or "__STATUS__=" not in cp.stdout:
        raise RuntimeError("Site request failed: " + path)
    body, status = cp.stdout.rsplit("__STATUS__=", 1)
    code, ctype = status.strip().split(":", 1)
    return int(code), ctype, body


def preflight(content: str) -> bool:
    if content.count(ANCHOR) != 1:
        raise RuntimeError("Blog location anchor changed; refusing nginx edit")
    if len(re.findall(r"server_name\\s+servgo\\.ru", content)) != 2:
        raise RuntimeError("Unexpected number of servgo.ru vhosts")
    if re.search(r"location\\s+\\^~\\s+/business/", content):
        raise RuntimeError("Higher-priority company location would bypass SSR")
    if content.count(MARK) not in (0, 1):
        raise RuntimeError("SEO SSR marker duplicated")
    if content.count(MARK) == 1 and "SERVGO_COMPANY_SEO_SSR_END" not in content:
        raise RuntimeError("Incomplete existing SSR route marker")
    test = run("nginx", "-t")
    if test.returncode:
        raise RuntimeError("Existing nginx config is invalid")
    for path in ("/api/seo-pages/sitemap.xml", "/sitemap.xml",
                 "/business-blog-sitemap.xml"):
        code, kind, body = request(path)
        if code != 200 or "xml" not in kind or "<" not in body:
            raise RuntimeError("Required XML endpoint unavailable: " + path)
    # The upstream is the source of truth. Its unknown company must be a true 404.
    for suffix in ("blog", "blog/sitemap.xml", "blog/definitely-not-a-real-article"):
        code, _, _ = request("/api/seo-pages/business/99999999/" + suffix)
        if code != 404:
            raise RuntimeError("Backend missing-page contract is broken: " + suffix)
    print("company_seo_preflight=ok", flush=True)
    return MARK in content


def smoke() -> None:
    for suffix in ("blog", "blog/sitemap.xml", "blog/definitely-not-a-real-article"):
        internal = "/api/seo-pages/business/99999999/" + suffix
        public = "/business/99999999/" + suffix
        backend_code, _, _ = request(internal)
        public_code, _, public_html = request(public)
        if backend_code != public_code or public_code != 404 or "seo-route-bootstrap" in public_html:
            raise RuntimeError("SSR path failed: " + public)
        print(f"public_company_seo_check={public} status={public_code}", flush=True)
    for path, root in (("/sitemap.xml", "<urlset"),
                       ("/business-blog-sitemap.xml", "<sitemapindex")):
        code, kind, xml = request(path)
        if code != 200 or "xml" not in kind or root not in xml:
            raise RuntimeError("Sitemap XML changed during nginx update: " + path)
    for path in ("/", "/blog"):
        code, _, _ = request(path)
        if code != 200:
            raise RuntimeError("Existing public page affected: " + path)
    print("company_seo_nginx_smoke=passed", flush=True)


def apply() -> None:
    if not SITE.is_file() or SITE.is_symlink():
        raise RuntimeError("Unexpected production site file/symlink")
    content = SITE.read_text()
    installed = preflight(content)
    if installed:
        smoke()
        print("company_seo_nginx_already_installed=true", flush=True)
        return
    BACKUPS.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUPS / ("webapp-before-ssr-" + name)
    if backup.exists():
        raise RuntimeError("Backup collision")
    shutil.copy2(SITE, backup)
    print("company_seo_nginx_backup_created=true", flush=True)
    destination = content.replace(ANCHOR, SNIPPET + ANCHOR, 1)
    fd, temp = tempfile.mkstemp(prefix=".webapp-seo-", dir=SITE.parent)
    replaced = False
    try:
        with os.fdopen(fd, "w") as writer:
            writer.write(destination)
            writer.flush()
            os.fsync(writer.fileno())
        shutil.copymode(SITE, temp)
        os.replace(temp, SITE)
        replaced = True
        if run("nginx", "-t").returncode:
            raise RuntimeError("nginx -t failed after SEO location update")
        if run("systemctl", "reload", "nginx").returncode:
            raise RuntimeError("nginx reload failed")
        smoke()
    except BaseException:
        if replaced:
            shutil.copy2(backup, SITE)
            if run("nginx", "-t").returncode or run("systemctl", "reload", "nginx").returncode:
                print("company_seo_nginx_rollback=FAILED", flush=True)
                raise
            print("company_seo_nginx_rollback=ok", flush=True)
        raise
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print("company_seo_nginx_release=success", flush=True)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "inspect"
    if mode not in {"inspect", "apply"}:
        raise SystemExit("expected inspect or apply")
    if not SITE.is_file():
        raise RuntimeError("Production site missing")
    installed = preflight(SITE.read_text())
    print(f"company_seo_nginx_installed={str(installed).lower()}", flush=True)
    if mode == "apply":
        apply()


if __name__ == "__main__":
    main()
