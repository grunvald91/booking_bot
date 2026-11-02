"""Isolated, bounded, server-side 2GIS -> ClaudeHub -> SQLite smoke test.

Invoked only from the manually prepared scoped GitHub workflow. Never connects to
the production mail SQLite DB, Postgres, SMTP, Exa or Jev. No personal data in logs.
"""
import asyncio
import json
import os
import pathlib
import subprocess
import sys
import time
from uuid import uuid4


def load_allowed_server_environment():
    result = subprocess.run(
        ["systemctl", "show", "-p", "MainPID", "--value", "booking-web-api.service"],
        capture_output=True, text=True, timeout=8, check=True,
    )
    pid = int(result.stdout.strip())
    if pid <= 1:
        raise RuntimeError("Web API service MainPID unavailable")
    data = pathlib.Path("/proc/%s/environ" % pid).read_bytes()
    allowed = {
        "CLAUDEHUB_API_KEY", "XAI_API_KEY", "SERVGO_MAIL_AI_MODEL",
        "SERVGO_MAIL_AI_TIMEOUT", "STUDIO_INTERNAL_KEY",
        "GROWTH_INTERNAL_URL",
    }
    loaded = set()
    for item in data.split(b"\0"):
        if b"=" not in item:
            continue
        name, value = item.split(b"=", 1)
        key = name.decode("ascii", "ignore")
        if key in allowed and value:
            os.environ[key] = value.decode("utf-8", "surrogateescape")
            loaded.add(key)
    return bool({"CLAUDEHUB_API_KEY", "XAI_API_KEY"} & loaded)


async def run(stage):
    configured = load_allowed_server_environment()
    # Explicitly override ANY server setting that could cause writes outside this directory.
    private_data = stage / "scratch-data"
    private_data.mkdir(mode=0o700, exist_ok=True)
    private_data.chmod(0o700)
    os.environ.update({
        "SERVGO_MAIL_DATA_DIR": str(private_data),
        "DATABASE_URL": "postgresql+asyncpg://mail_smoke:invalid@127.0.0.1:1/never_connect",
        "BOT_TOKEN": "mail-test-token",
        "SERVGO_SEARCH_PAUSE_SECONDS": "5",
        "SERVGO_2GIS_MAX_PAGES": "1",
        "SERVGO_MAIL_USE_JEV": "false",
        "OPENROUTER_API_KEY": "",
        "EXA_API_KEY": "",
        "SERVGO_MAIL_AI_TIMEOUT": "60",
        "SERVGO_MAIL_AI_MAX_TOKENS": "4000",
    })
    os.chdir("/opt/booking_bot")
    sys.path.insert(0, "/opt/booking_bot")
    import web.api.routes as routes
    routes.__path__.insert(0, str(stage))
    from web.api.routes import mail_company_search as search
    from web.api.routes import owner_mail
    from web.api.routes import mail_campaign_api as campaigns
    from web.api.routes.mail_campaign_store import initialize as initialize_campaigns, utcnow

    started = time.monotonic()
    job_id = uuid4().hex
    niche, city = "салон красоты", "sochi"
    with owner_mail.db_open() as db:
        search.initialize(db)
        db.execute(
            "INSERT INTO search_job (id,niche,city,want,company_id,company_name,company_brief,"
            "provider,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, niche, city, None, "", "ServGo",
             json.dumps(search.SERVGO, ensure_ascii=False), "2gis", "running",
             utcnow(), utcnow()),
        )

    original_parse = search.parse_search_page
    page_info = {}

    def limited_first_page(html, page):
        result = original_parse(html, page)
        page_info.update(reported_total=result.total, reported_pages=result.pages,
                         first_page_cards=len(result.ids))
        result.ids = result.ids[:5]
        result.pages = 1  # ONLY isolated smoke-test, not a production restriction.
        return result

    search.parse_search_page = limited_first_page
    actual_judge = search.judge
    ai = {"attempts": 0, "returned_boolean": False, "duration_seconds": 0.0,
          "available": configured}

    async def one_real_judgment(card, brief):
        if ai["attempts"] or not configured:
            return None, "Пробный прогон: остальные оценки ИИ не выполнялись"
        ai["attempts"] = 1
        at = time.monotonic()
        try:
            fit, reason = await asyncio.wait_for(actual_judge(card, brief), timeout=80)
            ai["returned_boolean"] = fit in (0, 1)
            return fit, reason
        except Exception:
            return None, "Пробная проверка ИИ завершилась ошибкой"
        finally:
            ai["duration_seconds"] = round(time.monotonic() - at, 1)

    search.judge = one_real_judgment
    # Real 2GIS and one real ClaudeHub model decision, no emails sent.
    try:
        await asyncio.wait_for(search.run_job(job_id, niche, city, None, dict(search.SERVGO)),
                               timeout=180)
    except asyncio.TimeoutError:
        search._finish(job_id, "error", "Пробный запуск превысил лимит 180 секунд")

    # Reopen the SQLite file to verify results survived database commit/close.
    with owner_mail.db_open() as db:
        search.initialize(db)
        data = search._view(db, job_id)
        stored = db.execute("SELECT COUNT(*) FROM search_hit WHERE job_id=?", (job_id,)).fetchone()[0]
        stored_mail = db.execute(
            "SELECT COUNT(*) FROM search_hit WHERE job_id=? AND email!=''", (job_id,)
        ).fetchone()[0]
    imported = 0
    import_ok = None
    if stored_mail:
        # Internal import test, in scratch DB only. One hit is explicitly approved
        # for technical verification and MUST NOT represent a real marketing decision.
        lead = next(h for h in data["hits"] if h["email"])
        search.review_hit(job_id, lead["firm_id"], search.HitReview(fit=True), None)
        campaign_id = campaigns.create_campaign(
            campaigns.CampaignInput(name="Изолированная проверка импорта ServGo"), None
        )["id"]
        result = search.to_campaign(
            job_id, search.ToCampaign(campaign_id=campaign_id, firm_ids=[lead["firm_id"]]), None,
        )
        imported = result["added"]
        with owner_mail.db_open() as db:
            initialize_campaigns(db)
            rows = db.execute(
                "SELECT status FROM campaign_recipient WHERE campaign_id=?", (campaign_id,)
            ).fetchall()
            status = db.execute("SELECT status FROM campaign WHERE id=?", (campaign_id,)).fetchone()
        import_ok = bool(imported == 1 and len(rows) == 1
                         and rows[0]["status"] == "new" and status["status"] == "draft")

    summary = {
        "provider_key_available": configured,
        "server_exec_ok": True,
        "job_status": data["job"]["status"],
        "search_error": data["job"]["message"] if data["job"]["status"] != "done" else "",
        "page": page_info,
        "stored_cards": stored,
        "stored_emails": stored_mail,
        "sqlite_reopen_verified": stored == len(data["hits"]),
        "ai": ai,
        "isolated_campaign_imported": imported,
        "isolated_campaign_draft_only": import_ok,
        "production_database_written": False,
        "messages_sent": 0,
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }
    print("SMOKE_RESULT " + json.dumps(summary, ensure_ascii=False), flush=True)
    return bool(data["job"]["status"] == "done" and stored > 0
                and summary["sqlite_reopen_verified"] and (not stored_mail or import_ok)
                and configured and ai["attempts"] == 1 and ai["returned_boolean"])


if __name__ == "__main__":
    stage = pathlib.Path(sys.argv[1]).resolve()
    try:
        passed = asyncio.run(run(stage))
        print("SMOKE_STATUS " + ("PASS" if passed else "PARTIAL"), flush=True)
        sys.exit(0 if passed else 2)
    except Exception as err:
        print("SMOKE_ERROR " + type(err).__name__, flush=True)
        if isinstance(err, ModuleNotFoundError):
            name = err.name or ""
            if name.replace("_", "").replace(".", "").isalnum():
                print("SMOKE_MISSING_MODULE " + name[:80], flush=True)
        print("SMOKE_STATUS FAIL", flush=True)
        sys.exit(3)
