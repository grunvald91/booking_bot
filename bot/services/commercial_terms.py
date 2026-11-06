"""Public ServGo subscription and onboarding terms for Telegram.

The caller passes the offer returned by webapp.niches.get_offer(), so the bot
never carries a second hard-coded price list.
"""

from html import escape
from typing import Any, Mapping


def format_commercial_terms(offer: Mapping[str, Any]) -> str:
    """Render concise HTML message using the shared promo landing offer."""
    entry_price = escape(str(offer["entry_price_text"]))
    studio_price = escape(str(offer["studio_price_text"]))
    free_places = int(offer["seats_total"])
    if free_places < 1:
        raise ValueError("seats_total must be positive")

    return (
        "💳 <b>Условия подключения ServGo</b>\n\n"
        "📅 <b>Онлайн-запись для бизнеса</b>\n"
        f"• Первые {free_places} бизнеса в каждой нише — подключение бесплатно, "
        "пока есть свободные места.\n"
        f"• Затем — <b>{entry_price} один раз</b> за внесение бизнеса.\n"
        "Вы получаете: размещение бизнеса и услуг, страницу онлайн-записи, "
        "расписание, напоминания, клиентскую базу и кабинет владельца. "
        "Учёт смен «Смена» включён. За эти инструменты нет ежемесячной платы.\n\n"
        f"✨ <b>Студия маркетинга — {studio_price} в месяц</b>\n"
        "Подготовка контент-плана и маркетинговых материалов для вашей ниши. "
        "Для первого бизнеса в нише может быть доступно бесплатное подключение "
        "студии, если акционное место ещё свободно.\n\n"
        "Наличие бесплатных мест и условия подключения уточняются по вашей нише."
    )
