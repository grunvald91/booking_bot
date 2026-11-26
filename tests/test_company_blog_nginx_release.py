"""Contract tests for the narrow, reversible ServGo public SEO nginx routing."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/ops/servgo_company_blog_nginx_release.py"
spec = spec_from_file_location("company_seo_nginx_release", PATH)
release = module_from_spec(spec)
spec.loader.exec_module(release)


def test_company_blog_location_catches_articles_sitemaps_and_invalid_paths():
    location = next(line.strip() for line in release.SNIPPET.splitlines()
                    if line.strip().startswith("location ~ ^/business/") and "(?:/|$)" in line)
    pattern = location.split("location ~ ", 1)[1].split(" {", 1)[0]
    for path in (
        "/business/1/blog", "/business/64/blog/",
        "/business/64/blog/sitemap.xml",
        "/business/64/blog/kak-uhazhivat-za-volosami",
        "/business/64/blog/__invalid_slug__",
    ):
        assert re.search(pattern, path), path
    for path in ("/business/64", "/business/64/blogger", "/blog/article", "/business/abc/blog"):
        assert not re.search(pattern, path), path


def test_only_public_company_blog_route_changes():
    assert release.SNIPPET.count("rewrite ") == 1
    assert "/seo-pages/business/$1/blog$2 break;" in release.SNIPPET
    assert "limit_except GET HEAD { deny all; }" in release.SNIPPET
    assert "SERVGO_COMPANY_SEO_SSR_BEGIN" in release.SNIPPET
    assert "location = /blog" in release.ANCHOR
    assert "proxy_pass http://127.0.0.1:8000;" in release.SNIPPET
    assert "proxy_intercept_errors off;" in release.SNIPPET


def test_nginx_accepts_public_seo_location_in_isolated_config(tmp_path):
    """The real nginx parser must accept our regex and rewrite directives."""
    nginx = shutil.which("nginx")
    if nginx is None:
        return  # Non-nginx developer systems; the PWA CI installs nginx before this test.
    path = tmp_path / "nginx.conf"
    path.write_text(
        "worker_processes 1;\n"
        "error_log stderr notice;\n"
        f"pid {tmp_path / 'nginx.pid'};\n"
        "events { worker_connections 128; }\n"
        "http { access_log off; server { listen 127.0.0.1:18080; server_name servgo.ru;\n"
        + release.SNIPPET +
        "location /api/ { return 200; }\n"
        "location / { return 200; }\n"
        "} }\n",
        encoding="utf-8",
    )
    result = subprocess.run([nginx, "-t", "-p", str(tmp_path) + "/", "-c", str(path)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr[-1200:]


def test_reload_retry_requires_success(monkeypatch):
    calls = []
    def smoke():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("old worker")
    monkeypatch.setattr(release, "smoke", smoke)
    monkeypatch.setattr(release.time, "sleep", lambda _: None)
    release.smoke_after_reload()
    assert len(calls) == 3


def test_persistent_smoke_failure_is_not_accepted(monkeypatch):
    import pytest
    calls = []
    def smoke():
        calls.append(1)
        raise RuntimeError("routing broken")
    monkeypatch.setattr(release, "smoke", smoke)
    monkeypatch.setattr(release.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="routing broken"):
        release.smoke_after_reload()
    assert len(calls) == 6


def test_nginx_live_proxy_preserves_path_and_404(tmp_path):
    import socket
    import time
    import urllib.request
    import urllib.error
    nginx = shutil.which("nginx")
    if nginx is None:
        return
    with socket.socket() as a, socket.socket() as b:
        a.bind(("127.0.0.1", 0))
        b.bind(("127.0.0.1", 0))
        front, back = a.getsockname()[1], b.getsockname()[1]
    config = tmp_path / "nginx.conf"
    snippet = release.SNIPPET.replace("127.0.0.1:8000", f"127.0.0.1:{back}")
    config.write_text(
        "worker_processes 1;\n"
        f"pid {tmp_path / 'nginx.pid'};\n"
        "error_log stderr notice;\n"
        "events { worker_connections 128; }\n"
        "http { access_log off;\n"
        f"client_body_temp_path {tmp_path / 'body'};\n"
        f"proxy_temp_path {tmp_path / 'proxy'};\n"
        f"fastcgi_temp_path {tmp_path / 'fastcgi'};\n"
        f"uwsgi_temp_path {tmp_path / 'uwsgi'};\n"
        f"scgi_temp_path {tmp_path / 'scgi'};\n"
        f"server {{ listen 127.0.0.1:{back};\n"
        "location = /seo-pages/business/64/blog/missing { return 404 'missing'; }\n"
        "location / { return 200 $request_uri; } }\n"
        f"server {{ listen 127.0.0.1:{front};\n"
        "proxy_intercept_errors on; error_page 404 =200 /index.html;\n"
        + snippet +
        "location / { return 200 'spa'; } } }\n",
        encoding="utf-8",
    )
    proc = subprocess.Popen([nginx, "-p", str(tmp_path) + "/", "-c", str(config),
                             "-g", "daemon off;"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f"http://127.0.0.1:{front}"
    try:
        for _ in range(40):
            try:
                with opener.open(base + "/", timeout=0.5) as response:
                    assert response.read() == b"spa"
                break
            except OSError:
                if proc.poll() is not None:
                    raise AssertionError("nginx exited")
                time.sleep(0.1)
        else:
            raise AssertionError("nginx did not start")
        with opener.open(base + "/business/64/blog/sitemap.xml?q=1", timeout=2) as response:
            assert response.read() == b"/seo-pages/business/64/blog/sitemap.xml?q=1"
        try:
            opener.open(base + "/business/64/blog/missing", timeout=2)
        except urllib.error.HTTPError as error:
            assert error.code == 404 and error.read() == b"missing"
        else:
            raise AssertionError("upstream 404 became SPA")
        with opener.open(base + "/business/64", timeout=2) as response:
            assert response.read() == b"spa"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
