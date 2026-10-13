"""Owner-only campaign dashboard, delivered under the mail subdomain API proxy."""
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from .owner_mail import mail_owner

router = APIRouter(prefix="/owner-mail", tags=["mail-campaign-ui"])


@router.get("/api/campaigns-dashboard")
def campaign_dashboard(_=Depends(mail_owner)):
    return FileResponse(
        Path(__file__).with_name("mail_campaign_dashboard.html"),
        media_type="text/html",
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
            ),
        },
    )
