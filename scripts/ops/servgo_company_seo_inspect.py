#!/usr/bin/env python3
"""Read-only local inspection of public company blog SEO chain (no changes)."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def check(path: str, host: str = "servgo.ru") -> None:
    args = ["curl", "-ksS", "--max-time", "10", "--resolve",
            f"{host}:443:127.0.0.1", "-w", "\n__CODE__%{http_code}",
            f"https://{host}{path}"]
    cp = subprocess.run(args, capture_output=True, text=True, timeout=16)
    if cp.returncode or "__CODE__" not in cp.stdout:
        print(f"probe={host}{path} error=curl_{cp.returncode}")
        return
    body, code = cp.stdout.rsplit("__CODE__", 1)
    print(f"probe={host}{path} code={code.strip()} "
          f"xml={body.lstrip().startswith('<?xml')} "
          f"spa={int('seo-route-bootstrap' in body)} "
          f"canonical={int('rel=\"canonical\"' in body)} "
          f"bytes={len(body.encode('utf-8'))}")


def growth_counts() -> None:
    code = """from app.db.session import SessionLocal
from app.models.domain import Publication, Artifact, ArtifactStatus
from app.sso.models import StudioBusinessLink
from sqlalchemy import select
with SessionLocal() as db:
    pairs = db.execute(select(Publication.product_id, Publication.artifact_id)
      .join(Artifact, Artifact.id == Publication.artifact_id)
      .where(Publication.channel == 'own_site', Publication.status == 'published',
        Artifact.status == ArtifactStatus.PUBLISHED, Artifact.kind == 'article')).all()
    links = {p for p in db.scalars(select(StudioBusinessLink.product_id)).all()}
    prods = {p for p, _ in pairs}
    print('growth_published_articles=' + str(len(pairs)))
    print('growth_published_products=' + str(len(prods)))
    print('growth_linked_published_products=' + str(len(prods & links)))
    print('growth_unlinked_published_products=' + str(len(prods - links)))
    print('growth_studio_links_total=' + str(len(links)))
    article_states = db.execute(select(Artifact.product_id, Artifact.status)
        .where(Artifact.kind == 'article')).all()
    tenant_artifacts = [(p, state) for p, state in article_states if p in links]
    print('linked_company_article_artifacts=' + str(len(tenant_artifacts)))
    print('linked_company_published_article_artifacts=' + str(sum(
        state == ArtifactStatus.PUBLISHED for _, state in tenant_artifacts)))
"""
    result = subprocess.run(["docker", "exec", "-i", "ai-growth-os-api-1",
                            "python", "-c", code],
                            capture_output=True, text=True, timeout=20)
    if result.returncode:
        print("growth_counts=unavailable")
    else:
        print(result.stdout.strip())


def main() -> None:
    site = Path("/etc/nginx/sites-enabled/webapp")
    print(f"site_exists={site.exists()} site_symlink={site.is_symlink()}")
    if site.exists():
        text = site.read_text()
        print(f"site_source={site.resolve()} bytes={len(text)}")
        for line in text.splitlines():
            stripped = line.strip()
            if re.match(r"^(server_name|listen|location|root|try_files)\b", stripped):
                print("nginx_directive=" + stripped[:230])
        print("seo_locations=" + str(len(re.findall(r"location\s+[^\n]*business/[^\n]*blog", text))))
    conf = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    print(f"nginx_valid={conf.returncode == 0}")
    for route in ("/api/seo-pages/sitemap.xml", "/api/seo-pages/business/1/blog",
                  "/api/seo-pages/business/1/blog/sitemap.xml",
                  "/business/1/blog", "/business/1/blog/sitemap.xml",
                  "/business-blog-sitemap.xml"):
        check(route)
    check("/public/blog/businesses/with-articles", host="growth.servgo.ru")
    growth_counts()


if __name__ == "__main__":
    main()
