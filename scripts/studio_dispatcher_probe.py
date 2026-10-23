"""Ask the studio dispatcher a list of owner questions on the production server and print how it answers.

Runs INSIDE the studio api container (`docker exec -i ai-growth-os-api-1 python -`), with the container's own
settings, model key and ServGo link. Nothing is published or created for the owner:
* only read capabilities are executed; anything else is printed as «WOULD_RUN» and not carried out;
* if business 11 has no company in the studio yet, a temporary one is created and deleted again at the end
  (together with everything the probe wrote for it); an existing company is only used, its conversation of the
  probe account is removed afterwards;
* table cells (client names, phones) are never printed, only table sizes.
"""
import asyncio
import json
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete, func, select

import app.models  # noqa: F401  registers every table
from app.api.dispatcher import get_dispatcher_llm
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal
from app.dispatcher import service
from app.dispatcher.executors import Context
from app.dispatcher.models import DispatcherConversation, DispatcherMessage
from app.dispatcher.outcome import Outcome
from app.models.domain import CostRecord, Product
from app.sso.models import StudioBusinessLink

BUSINESS_ID = 11
ACCOUNT = "probe-claude"
READ_ONLY = {"show_schedule", "show_work", "show_review", "show_plan", "go_to", "show_material"}
QUESTIONS = [
    "Что у меня сегодня?",
    "Кто следующий клиент?",
    "Сколько записей на завтра?",
    "Покажи свободные окна на неделю",
    "Какая загрузка яхт на неделю?",
    "Какая яхта загружена меньше всех?",
    "Какие заявки ждут моего подтверждения?",
    "Сколько отмен за последнее время?",
    "Сколько я заработаю на этой неделе?",
    "В какие дни недели у меня пустуют яхты?",
    "Почему в будни мало клиентов?",
    "Как мне увеличить количество клиентов?",
    "Проанализируй загрузку и скажи, какое одно простое действие даст больше всего новых клиентов",
    "Кто мои постоянные клиенты и кому написать, чтобы они вернулись?",
]


def summary(blocks):
    parts = []
    for block in blocks or []:
        kind = block.get("type")
        if kind == "table":
            parts.append(f"table {len(block.get('rows') or [])}x{len(block.get('columns') or [])} cols={block.get('columns')}")
        elif kind == "chips":
            parts.append("chips=" + " | ".join(str(i.get("label")) for i in block.get("items") or []))
        elif kind != "text":
            parts.append(str(kind))
    return "; ".join(parts) or "-"


async def main():
    settings = get_settings()
    llm = get_dispatcher_llm(settings)
    if llm is None:
        print("no model configured; stop")
        return
    original = service.act

    async def guarded(ctx, capability_id, raw_params):
        if capability_id not in READ_ONLY:
            print(f"   WOULD_RUN {capability_id} {json.dumps(raw_params, ensure_ascii=False)[:200]}")
            return Outcome(text="[проба: действие не выполнялось]"), None, capability_id
        return await original(ctx, capability_id, raw_params)

    service.act = guarded
    db = SessionLocal()
    link = db.scalar(select(StudioBusinessLink).where(StudioBusinessLink.servgo_business_id == BUSINESS_ID))
    created = False
    if link is not None:
        product = db.get(Product, link.product_id)
        print(f"company_exists=yes slug_enabled={product.slug in settings.dispatcher_enabled_slugs.split(',')}")
    else:
        product = Product(name="Проба диспетчера: заведение 11", slug="probe-" + uuid4().hex[:10],
                          description="Временная компания для пробы диспетчера; будет удалена.")
        db.add(product)
        db.flush()
        db.add(StudioBusinessLink(servgo_business_id=BUSINESS_ID, product_id=product.id))
        db.commit()
        created = True
        print("company_exists=no; temporary company created")
    ctx = Context(db=db, product=product, settings=settings, account=ACCOUNT)
    try:
        for number, question in enumerate(QUESTIONS, start=1):
            print(f"\n[{number}] {question}")
            try:
                result = await service.handle_message(db, ctx, llm, text=question, client_key=None)
            except Exception as error:  # noqa: BLE001 - the probe must go on with the next question
                print(f"   ERROR {type(error).__name__}")
                db.rollback()
                continue
            answer = next((m for m in result["messages"] if m["role"] == "assistant"), None)
            row = db.scalar(select(DispatcherMessage).where(DispatcherMessage.id == answer["id"])) if answer else None
            if row is None:
                print("   no answer")
                continue
            print(f"   intent={row.intent} capability={row.capability} confidence={row.confidence} model={row.model}")
            print(f"   params={json.dumps(row.params, ensure_ascii=False)[:200]}")
            print(f"   reply: {row.text}")
            print(f"   blocks: {summary(row.blocks)}")
        spent = db.scalar(select(func.coalesce(func.sum(CostRecord.amount), 0)).where(CostRecord.product_id == product.id))
        calls = db.scalar(select(func.count()).select_from(CostRecord).where(CostRecord.product_id == product.id))
        print(f"\nmodel_calls={calls} cost_usd={Decimal(spent):.4f}")
    finally:
        service.act = original
        db.rollback()
        if created:
            for table in reversed(Base.metadata.sorted_tables):
                if "product_id" in table.c:
                    db.execute(delete(table).where(table.c.product_id == product.id))
            db.execute(delete(Product).where(Product.id == product.id))
            db.commit()
            print("temporary company and everything the probe wrote for it: deleted")
        else:
            conversations = db.scalars(select(DispatcherConversation.id).where(
                DispatcherConversation.product_id == product.id, DispatcherConversation.account == ACCOUNT)).all()
            if conversations:
                db.execute(delete(DispatcherMessage).where(DispatcherMessage.conversation_id.in_(conversations)))
                db.execute(delete(DispatcherConversation).where(DispatcherConversation.id.in_(conversations)))
            db.commit()
            print("probe conversation deleted")


asyncio.run(main())
