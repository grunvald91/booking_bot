"""Can an LLM behind ClaudeHub find real prospects? Every claim is checked against the live web.

Runs inside the AI Growth OS container (uses its XAI_API_KEY / XAI_BASE_URL; never prints them).
Configs: kimi-k3 plain, kimi-k3 with Moonshot's builtin $web_search tool, grok-4.7 plain.
Per company: site opens, company name appears on it, email is published on the site,
a contact page or the cited source URL. Prints aggregates and masked per-row lines only.
"""
import json, os, re, time, urllib.parse
import httpx

BASE = os.environ.get("XAI_BASE_URL", "https://api.claudehub.fun/v1").rstrip("/")
KEY = os.environ.get("XAI_API_KEY", "")
NICHES = [("dental clinics", "Limassol, Cyprus"),
          ("barbershops", "Dubai Marina, Dubai, UAE"),
          ("yoga studios", "Lisbon, Portugal")]
CONFIGS = [("kimi-k3", False), ("kimi-k3", True), ("grok-4.7", False)]
PROMPT = ("Find 5 real, currently operating {niche} in {city}. For each give: name, website (full URL), "
          "a public contact email, source_url (the page where that email is published) and need_signal "
          "(one observable sign they could use an online booking system, e.g. 'booking by phone only'). "
          "Only include businesses you can verify; return fewer rather than guess. "
          'Reply with JSON only: {{"companies":[{{"name":"","website":"","email":"","source_url":"","need_signal":""}}]}}')
DEBUG = os.environ.get("EVAL_DEBUG") == "1"
if DEBUG:
    NICHES = NICHES[2:]
    CONFIGS = [("kimi-k3", False), ("kimi-k3", True)]
UA = {"User-Agent": "Mozilla/5.0 (compatible; ServGoProspectCheck/1.0)"}


def chat(model, use_search, prompt):
    msgs = [{"role": "user", "content": prompt}]
    body = {"model": model, "messages": msgs, "max_tokens": 2500, "temperature": 0.2}
    if use_search:
        body["tools"] = [{"type": "builtin_function", "function": {"name": "$web_search"}}]
    searched = 0
    with httpx.Client(timeout=180) as c:
        for _ in range(5):
            r = c.post(BASE + "/chat/completions", json=body, headers={"Authorization": "Bearer " + KEY})
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}: {r.text[:200]}", searched
            data = r.json()
            choice = data["choices"][0]
            msg = choice["message"]
            calls = msg.get("tool_calls") or []
            if DEBUG:
                print(f"    debug: finish={choice.get('finish_reason')} calls={[ (c.get('type'), c['function'].get('name'), c['function'].get('arguments','')[:160]) for c in calls]} "
                      f"content_head={(msg.get('content') or '')[:300]!r} extra_keys={sorted(k for k in msg if k not in ('role','content','tool_calls'))} usage={data.get('usage')}")
            if choice.get("finish_reason") == "tool_calls" and calls:
                msgs.append(msg)
                for call in calls:
                    searched += 1
                    msgs.append({"role": "tool", "tool_call_id": call["id"], "name": call["function"]["name"],
                                 "content": call["function"]["arguments"]})
                body["messages"] = msgs
                continue
            return msg.get("content") or "", None, searched
    return None, "too many tool rounds", searched


def parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0)).get("companies", []) if m else []
    except Exception:
        return []


def fetch(url):
    try:
        with httpx.Client(timeout=12, follow_redirects=True, headers=UA, verify=True) as c:
            r = c.get(url)
            return r.status_code, r.text[:600000].lower(), str(r.url)
    except Exception as e:
        return None, "", type(e).__name__


def check(co):
    site = (co.get("website") or "").strip()
    email = (co.get("email") or "").strip().lower()
    name = (co.get("name") or "").strip().lower()
    if site and not site.startswith("http"):
        site = "https://" + site
    st, html, final = fetch(site) if site else (None, "", "")
    alive = st is not None and st < 400
    words = [w for w in re.findall(r"[a-zа-я0-9]{4,}", name) if w not in {"clinic", "dental", "studio", "yoga", "barber", "barbershop", "shop"}]
    name_on_site = alive and bool(words) and any(w in html for w in words[:3])
    pages = [html]
    if alive and email and email not in html:
        for path in ("/contact", "/contacts", "/contact-us", "/en/contact", "/about"):
            s2, h2, _ = fetch(urllib.parse.urljoin(final, path))
            if s2 and s2 < 400:
                pages.append(h2)
                if email in h2:
                    break
    src = (co.get("source_url") or "").strip()
    if email and src.startswith("http") and not any(email in p for p in pages):
        s3, h3, _ = fetch(src)
        if s3 and s3 < 400:
            pages.append(h3)
    email_ok = bool(email) and any(email in p for p in pages)
    return {"alive": alive, "name_on_site": name_on_site, "email_published": email_ok,
            "email_given": bool(email), "status": st if st is not None else final}


def mask(e):
    return re.sub(r"^[^@]{1,}", lambda m: m.group(0)[:1] + "***", e or "")


if not KEY:
    raise SystemExit("XAI_API_KEY is not set in this container")
summary = {}
for model, search in CONFIGS:
    label = model + (" +$web_search" if search else "")
    tot = {"returned": 0, "alive": 0, "name_on_site": 0, "email_given": 0, "email_published": 0, "searches": 0, "errors": 0, "seconds": 0}
    print(f"\n=== {label}")
    for niche, city in NICHES:
        t = time.time()
        text, err, searched = chat(model, search, PROMPT.format(niche=niche, city=city))
        tot["seconds"] += round(time.time() - t)
        tot["searches"] += searched
        if err:
            tot["errors"] += 1
            print(f"  [{niche} / {city}] ERROR {err}")
            continue
        cos = parse(text)[:5]
        print(f"  [{niche} / {city}] returned {len(cos)}, tool searches {searched}")
        for co in cos:
            r = check(co)
            tot["returned"] += 1
            for k in ("alive", "name_on_site", "email_given", "email_published"):
                tot[k] += int(r[k])
            print(f"    - {co.get('name','')[:40]:40} site={'OK' if r['alive'] else r['status']} name={'Y' if r['name_on_site'] else 'n'} "
                  f"email={mask(co.get('email',''))} published={'Y' if r['email_published'] else 'n'} | need: {(co.get('need_signal') or '')[:60]}")
    summary[label] = tot
print("\n=== SUMMARY (verified against the live web)")
for label, t in summary.items():
    n = t["returned"] or 1
    print(f"{label:22} returned={t['returned']:2} site_opens={t['alive']*100//n}% name_on_site={t['name_on_site']*100//n}% "
          f"email_given={t['email_given']*100//n}% email_verified={t['email_published']*100//n}% tool_searches={t['searches']} errors={t['errors']} time={t['seconds']}s")
