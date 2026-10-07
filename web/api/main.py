"""
BookingBot API — FastAPI backend for the booking service.
Works with the same PostgreSQL database as the Telegram bot.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import client, admin, auth, ai, subscriptions, notifications, email_auth, payments, telegram_link
from . import rental

app = FastAPI(
    title="BookingBot API",
    description="API for SochiService booking platform",
    version="1.0.0",
    root_path="/api",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(email_auth.router, prefix="/auth", tags=["auth"])
app.include_router(telegram_link.router, prefix="/auth", tags=["auth"])
app.include_router(payments.router, prefix="/admin", tags=["admin"])
app.include_router(client.router, tags=["client"])
app.include_router(rental.router, tags=["rental"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(ai.router, tags=["ai"])
app.include_router(subscriptions.router, tags=["subscriptions"])
app.include_router(notifications.router, prefix="/notifications", tags=["notifications"])


@app.get("/health")
async def health():
    return {"status": "ok"}
