"""Rate-limited delivery of owner-approved campaign messages.

A dedicated single worker invokes dispatch_one. SMTP retries for ambiguous outcomes
are intentionally disabled, preventing duplicate deliveries after network timeouts.
"""
from __future__ import annotations

import asyncio
import email.utils
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr

from .mail_campaign_store import audit, initialize, utcnow
from .owner_mail import ADDRESS, db_open, sign


def reserve_send():
    sender = os.getenv("SERVGO_MAIL_FROM", "").strip()
    if not ADDRESS.fullmatch(sender):
        return None
    limit = max(1, min(500, int(os.getenv("SERVGO_MAIL_DAILY_LIMIT", "50"))))
    current = datetime.now(timezone.utc)
    earlier = (current - timedelta(hours=24)).isoformat()
    with db_open() as db:
        initialize(db)
        db.execute("BEGIN IMMEDIATE")
        attempts = db.execute(
            "SELECT count(*) FROM campaign_event WHERE event='send_attempt' "
            "AND occurred_at>=?", (earlier,),
        ).fetchone()[0]
        if attempts >= limit:
            return None
        candidate = db.execute("""
            SELECT r.*, c.min_interval_seconds
            FROM campaign_recipient r
            JOIN campaign c ON c.id=r.campaign_id
            WHERE r.status='approved' AND c.status='running'
              AND (c.not_before='' OR c.not_before<=?)
              AND NOT EXISTS (SELECT 1 FROM campaign_exclusions x WHERE x.email=r.email)
            ORDER BY r.created_at,r.id LIMIT 1
        """, (current.isoformat(),)).fetchone()
        if not candidate:
            return None
        last = db.execute(
            "SELECT max(occurred_at) AS last_time FROM campaign_event "
            "WHERE event='send_attempt'"
        ).fetchone()["last_time"]
        if last and (current-datetime.fromisoformat(last)).total_seconds() < max(
                30, candidate["min_interval_seconds"]):
            return None
        message_id = "<sgc-" + candidate["id"] + "@servgo.ru>"
        changed = db.execute(
            "UPDATE campaign_recipient SET status='sending',reserved_at=?,"
            "message_id=? WHERE id=? AND status='approved'",
            (current.isoformat(), message_id, candidate["id"]),
        )
        if changed.rowcount != 1:
            return None
        audit(db, candidate["campaign_id"], "send_attempt", candidate["id"])
        return dict(candidate), sender, message_id


def make_message(row, sender, message_id):
    msg = EmailMessage()
    msg["From"] = formataddr(("ServGo", sender))
    msg["To"] = row["email"]
    msg["Subject"] = row["subject"]
    msg["Date"] = email.utils.formatdate(localtime=False)
    msg["Message-ID"] = message_id
    msg["X-ServGo-Campaign"] = row["campaign_id"]
    msg.set_content(row["body"])
    token = sign(row["id"], "campaign-unsubscribe", 365 * 86400,
                 address=row["email"], campaign_id=row["campaign_id"])
    endpoint = "https://mail.servgo.ru/unsubscribe?token=" + token
    msg["List-Unsubscribe"] = "<" + endpoint + ">"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    return msg


def send_local_smtp(message, sender, recipient):
    with smtplib.SMTP("127.0.0.1", 25, timeout=20) as server:
        failed = server.send_message(
            message, from_addr=sender, to_addrs=[recipient],
        )
        if failed:
            raise smtplib.SMTPRecipientsRefused(failed)


async def dispatch_one() -> bool:
    reserved = reserve_send()
    if reserved is None:
        return False
    row, sender, message_id = reserved
    try:
        message = make_message(row, sender, message_id)
        await asyncio.to_thread(send_local_smtp, message, sender, row["email"])
        status, event = "accepted", "smtp_accepted"
    except (
        smtplib.SMTPRecipientsRefused,
        smtplib.SMTPRecipientRefused,
        smtplib.SMTPSenderRefused,
        smtplib.SMTPAuthenticationError,
        smtplib.SMTPHeloError,
        smtplib.SMTPNotSupportedError,
    ):
        status, event = "rejected", "smtp_rejected"
    except Exception:
        # A lost SMTP response may mean the remote server already accepted the mail.
        status, event = "unknown", "smtp_unknown"
    with db_open() as db:
        initialize(db)
        if status == "accepted":
            db.execute(
                "UPDATE campaign_recipient SET status=?,accepted_at=? WHERE id=?",
                (status, utcnow(), row["id"]),
            )
        else:
            db.execute(
                "UPDATE campaign_recipient SET status=? WHERE id=?",
                (status, row["id"]),
            )
        audit(db, row["campaign_id"], event, row["id"])
    return True
