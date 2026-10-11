# ServGo: search indexing release checklist

Main public React site: https://servgo.ru/ (web/frontend).
Separate marketing pages: https://promo.servgo.ru/ (webapp/server.py).
These are different hosts, with separate robots.txt and sitemap.xml files.

Changes: SEO title/description, canonical, Open Graph, Schema.org JSON-LD,
and search-readable fallback HTML in index.html; public robots.txt and sitemap.xml
for the main host. Only / is included in the sitemap: other application routes are
dynamic and currently lack unique server-rendered SEO content.

Before marking this issue resolved:
1. Independently check authoritative DNS and public DNS for servgo.ru and www:
   dig +short servgo.ru A; dig +short servgo.ru AAAA; dig +short www.servgo.ru CNAME
2. Check HTTPS/TLS and that http and www redirect (301/308) to https://servgo.ru/.
3. Deploy Vite build to the **actual** servgo.ru virtual host using SSH/Codespaces;
   verify correct vhost; do not assume web/nginx.conf describes production.
4. Verify homepage HTTP 200 with nonempty HTML, no X-Robots-Tag noindex,
   no login redirect, and no bot access challenge.
5. Check /robots.txt and /sitemap.xml return 200 with text/plain or XML,
   NOT the SPA fallback HTML. Check favicon and JS/CSS assets.
6. Check promo.servgo.ru similarly (it already has dynamic robots/sitemap
   and six niche landings in webapp/server.py).
7. Verify ownership in Yandex Webmaster and Google Search Console, add
   their respective sitemap URLs, inspect/request reindexing of important URLs.
8. Watch crawl/error/indexing coverage. Search visibility is not guaranteed.

Do not use GitHub Actions minutes for repeated exploratory deployments.
Git commits on a branch do NOT publish production changes.
