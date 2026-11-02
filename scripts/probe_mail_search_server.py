"""Run the ServGo mail smoke on the actual server without installing new production code.

Uses the existing pinned SSH key policy. Copies source files ONLY into /tmp and
removes them and their test SQLite database in a finally block. Does not restart
services, deploy changes, read or print secret values, or send any mail.
"""
import json
import os
import pathlib
import re
import shlex
import sys
from uuid import uuid4

from deploy_mail_search import connect


FILES = [
    "web/api/routes/mail_company_search.py",
    "web/api/routes/owner_mail.py",
    "web/api/routes/mail_campaign_api.py",
    "web/api/routes/mail_campaign_store.py",
    "web/api/routes/mail_campaign_research.py",
    "scripts/mail_isolated_server_smoke.py",
]


def command(client, shell, timeout=30):
    _, output, errors = client.exec_command(shell, timeout=timeout)
    data = output.read().decode("utf-8", "replace")
    result = output.channel.recv_exit_status()
    # Never propagate stderr: it may include environment or user data.
    return result, data


def main():
    if not os.getenv("SERVGO_PASSWORD"):
        raise RuntimeError("Missing configured GitHub Actions server password")
    client = connect()
    stage = "/tmp/servgo-mail-smoke-" + uuid4().hex
    try:
        code, status = command(
            client,
            "systemctl is-active booking-web-api.service && "
            "curl --silent --output /dev/null --write-out '%{http_code}' --max-time 8 "
            "http://127.0.0.1:8000/health",
        )
        preflight = status.strip().splitlines()
        if code != 0 or len(preflight) < 2 or preflight[0] != "active" or preflight[1] != "200":
            raise RuntimeError("API service health preflight failed")
        print("SMOKE_SERVER_PREFLIGHT health=200 service=active", flush=True)
        code, _ = command(client, "mkdir -m 700 " + shlex.quote(stage))
        if code:
            raise RuntimeError("Could not create isolated remote directory")
        with client.open_sftp() as sftp:
            for name in FILES:
                source = pathlib.Path(name)
                if not source.is_file():
                    raise RuntimeError("Missing local source: " + name)
                dest = stage + "/" + source.name
                sftp.put(str(source), dest)
                sftp.chmod(dest, 0o600)
        shell = (
            "cd /opt/booking_bot && /opt/booking_bot/venv/bin/python "
            + shlex.quote(stage + "/mail_isolated_server_smoke.py") + " "
            + shlex.quote(stage)
        )
        status, result = command(client, shell, timeout=250)
        safe_lines = [line for line in result.splitlines() if line.startswith("SMOKE_")]
        for line in safe_lines:
            if line.startswith("SMOKE_RESULT "):
                try:
                    report = json.loads(line[len("SMOKE_RESULT "):])
                    whitelist = {
                        "provider_key_available", "server_exec_ok", "job_status",
                        "search_error", "page", "stored_cards", "stored_emails",
                        "sqlite_reopen_verified", "ai", "isolated_campaign_imported",
                        "isolated_campaign_draft_only", "production_database_written",
                        "messages_sent", "elapsed_seconds",
                    }
                    report = {k: v for k, v in report.items() if k in whitelist}
                    print("SMOKE_RESULT " + json.dumps(report, ensure_ascii=False), flush=True)
                except Exception:
                    print("SMOKE_ERROR MalformedSummary", flush=True)
            elif re.fullmatch(r"SMOKE_STATUS (PASS|PARTIAL|FAIL)", line):
                print(line, flush=True)
            elif re.fullmatch(r"SMOKE_ERROR [A-Za-z]+", line):
                print(line, flush=True)
        if status != 0:
            raise RuntimeError("Server test did not pass; production unchanged")
        print("SMOKE_SERVER_TEST passed=true", flush=True)
    finally:
        if stage.startswith("/tmp/servgo-mail-smoke-") and len(stage) == 55:
            try:
                command(client, "rm -rf -- " + shlex.quote(stage), timeout=30)
                print("SMOKE_CLEANUP temporary_files_removed=true", flush=True)
            except Exception:
                print("SMOKE_CLEANUP temporary_files_removed=unknown", flush=True)
        client.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print("SMOKE_RUNNER_ERROR " + type(err).__name__ + ": " + str(err)[:120], flush=True)
        sys.exit(1)
