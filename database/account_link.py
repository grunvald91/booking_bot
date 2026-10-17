"""Two authenticated identities, one account. No phone/email matching or user deletion."""

from datetime_utils import utc_now
import hashlib
import uuid
from datetime import datetime

from sqlalchemy import select, update, text

from database.models import (User, EmailIdentity, EmailChallenge, TelegramLinkRequest, UserAccountMerge,
    Business, BusinessOwner, Booking, ClientSubscription, PushSubscription, SalesConversation)


class AccountLinkError(ValueError):
    pass


def link_token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


async def telegram_claim(db, token, telegram):
    request = await db.scalar(select(TelegramLinkRequest).where(TelegramLinkRequest.token_hash == link_token_hash(token)).with_for_update())
    if not request or request.consumed or request.expires_at <= utc_now():
        raise AccountLinkError("Ссылка недействительна или истекла. Запросите новую в кабинете")
    # Only an authenticated Telegram update calls this function, never a browser-supplied ID.
    if db.bind.dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": telegram.id})
    target = await db.scalar(select(User).where(User.telegram_id == telegram.id))
    if target is None:
        target = User(telegram_id=telegram.id, username=telegram.username, full_name=telegram.full_name)
        db.add(target); await db.flush()
    if request.telegram_user_id and request.telegram_user_id != target.id:
        raise AccountLinkError("Эта ссылка уже открыта другим Telegram-аккаунтом. Запросите новую")
    request.telegram_user_id = target.id
    return request


async def telegram_confirm(db, request_id, telegram_id):
    request = await db.scalar(select(TelegramLinkRequest).where(TelegramLinkRequest.id == request_id).with_for_update())
    if not request or request.consumed or request.expires_at <= utc_now():
        raise AccountLinkError("Запрос уже завершён или истёк")
    target = await db.get(User, request.telegram_user_id) if request.telegram_user_id else None
    if target is None or target.telegram_id != telegram_id:
        raise AccountLinkError("Подтверждать должен тот же Telegram-аккаунт, который открыл ссылку")
    request.telegram_confirmed = True
    return request


async def merge_email_into_telegram(db, request, source_user_id):
    """Called only after email password re-authentication AND Telegram confirmation."""
    if request.user_id != source_user_id or request.consumed or request.expires_at <= utc_now() or not request.telegram_confirmed:
        raise AccountLinkError("Привязка не подтверждена или истекла")
    users = list((await db.execute(select(User).where(User.id.in_([source_user_id, request.telegram_user_id]))
        .order_by(User.id).with_for_update().execution_options(populate_existing=True))).scalars())
    by_id = {u.id: u for u in users}
    source, target = by_id.get(source_user_id), by_id.get(request.telegram_user_id)
    if source is None or target is None or source.id == target.id or source.telegram_id > 0 or target.telegram_id <= 0:
        raise AccountLinkError("Этот аккаунт уже связан с Telegram")
    identities = list((await db.execute(select(EmailIdentity).where(EmailIdentity.user_id.in_([source.id, target.id]))
        .order_by(EmailIdentity.email).with_for_update().execution_options(populate_existing=True))).scalars())
    identity = next((i for i in identities if i.user_id == source.id), None)
    if identity is None or identity.session_version != request.email_session_version:
        raise AccountLinkError("Сессия email изменилась. Войдите заново и запросите новую привязку")
    if any(i.user_id == target.id for i in identities):
        raise AccountLinkError("Telegram уже связан с другой подтверждённой почтой. Обратитесь в поддержку")
    if await db.get(UserAccountMerge, source.id) or await db.get(UserAccountMerge, target.id):
        raise AccountLinkError("Аккаунт уже объединён. Войдите заново")
    # Preserve an existing paid/manual-owner entitlement; don't guess between two paid plans.
    if source.subscription_status != "none" or source.is_manual_owner:
        if target.subscription_status != "none" or target.is_manual_owner:
            raise AccountLinkError("У обоих аккаунтов есть подписки. Объединение должен проверить оператор")
        for name in ("tariff", "max_businesses", "subscription_status", "subscription_expires", "is_manual_owner"):
            setattr(target, name, getattr(source, name))
    target.is_admin = target.is_admin or source.is_admin
    target.email = identity.email
    if not target.phone:
        target.phone = source.phone

    # Assets keep their IDs/statuses; only the owning user reference changes.
    for model, column in ((Business, Business.owner_id), (Booking, Booking.client_id),
                          (ClientSubscription, ClientSubscription.client_id), (PushSubscription, PushSubscription.user_id)):
        await db.execute(update(model).where(column == source.id).values({column.key: target.id}))
    memberships = list((await db.execute(select(BusinessOwner).where(BusinessOwner.user_id.in_([source.id, target.id]))
        .order_by(BusinessOwner.id).with_for_update())).scalars())
    target_memberships = {o.business_id: o for o in memberships if o.user_id == target.id}
    for member in [o for o in memberships if o.user_id == source.id]:
        existing = target_memberships.get(member.business_id)
        if existing:
            if member.role == "owner": existing.role = "owner"
            await db.delete(member)
        else:
            member.user_id = target.id
            target_memberships[member.business_id] = member
    threads = list((await db.execute(select(SalesConversation).where(SalesConversation.principal.in_([
        f"user:{source.id}", f"user:{target.id}"])).order_by(SalesConversation.id).with_for_update())).scalars())
    target_businesses = {t.business_id for t in threads if t.principal == f"user:{target.id}"}
    for thread in [t for t in threads if t.principal == f"user:{source.id}"]:
        thread.principal = f"archive:merged:{source.id}:{uuid.uuid4().hex}" if thread.business_id in target_businesses else f"user:{target.id}"
        # Invalidate an unconfirmed card whose booking principal changed; preserve conversation text.
        if thread.action and thread.action.get("status") != "completed":
            thread.action = None; thread.action_id = None
    identity.user_id = target.id
    identity.session_version += 1
    db.add(UserAccountMerge(source_user_id=source.id, target_user_id=target.id))
    await db.execute(update(EmailChallenge).where(EmailChallenge.user_id == source.id).values(consumed=True))
    await db.execute(update(TelegramLinkRequest).where(TelegramLinkRequest.user_id == source.id).values(consumed=True))
    request.consumed = True
    await db.flush()
    return identity
