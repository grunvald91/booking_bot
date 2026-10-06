"""Tenant-bound catalog and booking adapters; business/client IDs never come from the LLM."""
from __future__ import annotations

import json
from datetime import date as Date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from database.models import Business, Service, Employee, EmployeeService, EmployeeDayOff, Booking, VenueTimePricing
from database.booking_safety import lock_resource_days
from .. import rental
from ..routes import client
from ..rental_logic import price_quote
from ..schemas import CreateBookingIn
from .policy import policy_for, SalesPolicy
from .schedule import resource_works


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogArgs(ToolArgs):
    query: str = Field(default="", max_length=200)


class ServiceArgs(ToolArgs):
    service_id: int = Field(gt=0)


class PriceArgs(ServiceArgs):
    employee_id: int | None = Field(default=None, gt=0)
    duration_hours: int | None = Field(default=None, ge=1, le=12)
    additional_service_ids: list[int] = Field(default_factory=list, max_length=8)
    date: Date | None = None
    time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")


class AvailabilityArgs(ServiceArgs):
    date: Date
    employee_id: int | None = Field(default=None, gt=0)
    duration_hours: int | None = Field(default=None, ge=1, le=12)


class BookingArgs(AvailabilityArgs):
    employee_id: int = Field(gt=0)
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    additional_service_ids: list[int] = Field(default_factory=list, max_length=8)


class HandoffArgs(ToolArgs):
    reason: str = Field(min_length=1, max_length=500)


ARG_MODELS = {
    "get_services": CatalogArgs, "get_service_details": ServiceArgs,
    "get_prices": PriceArgs, "get_specialists": ServiceArgs,
    "check_availability": AvailabilityArgs, "create_booking": BookingArgs,
    "handoff_to_human": HandoffArgs, "get_my_bookings": ToolArgs,
}
DESCRIPTIONS = {
    "get_services": "Каталог услуг выбранной компании. Начни с него, не придумывай услуги.",
    "get_service_details": "Описание, длительность, инструкции и ограничения реальной услуги.",
    "get_prices": "Реальная цена услуги/аренды и необходимость согласования менеджером. Для аренды укажи ресурс и часы.",
    "get_specialists": "Активные специалисты/ресурсы, которые оказывают выбранную услугу.",
    "check_availability": "Реальные свободные окна по услуге, дате и ресурсу. Для аренды нужны duration_hours.",
    "create_booking": "Подготовь карточку записи после выбора услуги, специалиста и времени. Не создаёт запись до подтверждения клиентом.",
    "handoff_to_human": "Передай диалог оператору по просьбе клиента или когда требуется человек. ИИ замолчит до возврата оператором.",
    "get_my_bookings": "Покажи записи авторизованного клиента в выбранной компании и ссылки для управления ими.",
}
TOOL_SCHEMAS = [{"type": "function", "function": {
    "name": name, "description": DESCRIPTIONS[name], "parameters": model.model_json_schema(),
}} for name, model in ARG_MODELS.items()]


class ServGoTools:
    def __init__(self, db, business: Business, user=None):
        self.db, self.business, self.user = db, business, user
        self.policy = policy_for(business)

    async def require_tool(self, name):
        saved = (await self.db.execute(select(Business.sales_agent_settings)
            .where(Business.id == self.business.id))).scalar_one()
        self.policy = SalesPolicy.model_validate((saved or {}).get("policy", {}))
        self.policy.require(name)

    async def service(self, service_id: int) -> Service:
        service = (await self.db.execute(select(Service).where(
            Service.id == service_id, Service.business_id == self.business.id,
            Service.is_active.is_(True)))).scalar_one_or_none()
        if not service:
            raise HTTPException(404, "Услуга не найдена в выбранной компании")
        return service

    async def employee(self, employee_id: int, service: Service) -> Employee:
        employees = await self.specialists(service)
        employee = next((e for e in employees if e.id == employee_id), None)
        if not employee:
            raise HTTPException(404, "Специалист не оказывает эту услугу в выбранной компании")
        return employee

    async def specialists(self, service: Service) -> list[Employee]:
        employees = (await self.db.execute(select(Employee).where(
            Employee.business_id == self.business.id, Employee.is_active.is_(True),
            Employee.role != "administrator").order_by(Employee.id))).scalars().all()
        links = (await self.db.execute(select(EmployeeService.employee_id, EmployeeService.service_id)
            .join(Employee, Employee.id == EmployeeService.employee_id)
            .where(Employee.business_id == self.business.id))).all()
        by_employee = {}
        for employee_id, service_id in links:
            by_employee.setdefault(employee_id, set()).add(service_id)
        allowed = None
        if service.available_employee_ids:
            try:
                allowed = set(json.loads(service.available_employee_ids))
            except (ValueError, TypeError):
                return []  # Invalid configuration cannot make all resources eligible.
        return [e for e in employees
                if (not by_employee.get(e.id) or service.id in by_employee[e.id])
                and (allowed is None or e.id in allowed)]

    @staticmethod
    def service_data(service):
        return {"id": service.id, "name": service.name, "description": service.description,
                "duration_minutes": service.duration_minutes, "price": service.price,
                "is_additional": service.is_additional, "pricing_type": service.pricing_type,
                "tariff_description": service.tariff_description,
                "instructions": (service.ai_instruction or "")[:3000]}

    async def addons(self, ids: list[int]) -> list[Service]:
        if len(ids) != len(set(ids)):
            raise HTTPException(422, "Дополнительные услуги не должны повторяться")
        services = [await self.service(service_id) for service_id in ids]
        if any(not service.is_additional for service in services):
            raise HTTPException(422, "Выбрана неверная дополнительная услуга")
        return services

    async def quote(self, args: PriceArgs) -> dict:
        service = await self.service(args.service_id)
        employee = await self.employee(args.employee_id, service) if args.employee_id else None
        addons = await self.addons(args.additional_service_ids)
        result = {"service_id": service.id, "currency": "RUB", "amount": service.price,
                  "duration_minutes": service.duration_minutes, "price_requires_confirmation": False,
                  "booking_supported": True, "booking_url": f"/book/{self.business.id}"}
        if self.business.business_type == "venue_rental":
            if employee and employee.solo_price_per_hour and args.duration_hours:
                total, needs_quote, _ = price_quote(employee.solo_price_per_hour, args.duration_hours,
                                                   [s.price or 0 for s in addons])
                needs_quote = needs_quote or any(s.price is None for s in addons)
                result.update(amount=None if needs_quote else total,
                              duration_minutes=args.duration_hours * 60,
                              price_requires_confirmation=needs_quote)
            else:
                result.update(amount=None, price_requires_confirmation=True, booking_supported=False)
                if employee and args.time and args.date:
                    quote = await client.calculate_price(self.business.id, employee.id, args.time,
                        service.duration_minutes, args.date.isoformat(), self.db)
                    if quote.has_time_price:
                        result["estimated_amount"] = quote.total
            # Rental API owns both quote and booking rules. A different rental
            # tariff must go through its existing form/operator, never fixed-price booking.
            if not employee or not employee.solo_price_per_hour or not args.duration_hours:
                result["booking_supported"] = False
        elif (service.pricing_type not in (None, "fixed") or service.tariff_description
              or service.price is None or service.is_hourly_price or service.duration_minutes <= 0):
            result.update(amount=None, price_requires_confirmation=True, booking_supported=False)
        elif addons:
            if any(s.price is None or s.is_hourly_price or s.pricing_type not in (None, "fixed") or s.tariff_description for s in addons):
                result.update(amount=None, price_requires_confirmation=True, booking_supported=False)
            else:
                result["amount"] = service.price + sum(s.price for s in addons)
        if employee and self.business.business_type != "venue_rental":
            rules = (await self.db.execute(select(VenueTimePricing.id)
                .where(VenueTimePricing.employee_id == employee.id).limit(1))).first()
            if rules:
                result.update(price_requires_confirmation=True, booking_supported=False)
        if (self.business.working_hours_start and self.business.working_hours_end
            and self.business.working_hours_end <= self.business.working_hours_start):
            # Existing SlotOut carries only HH:MM, so next-day starts cannot be
            # safely confirmed against the requested calendar date by this adapter.
            result["booking_supported"] = False
        result["prepayment_percent"] = (
            None if self.business.business_type == "venue_rental"
            else (self.business.prepayment_percent or 100) if self.business.prepayment_enabled else 0)
        result["receipt_required"] = bool(self.business.require_receipt_for_prepayment)
        result["payment_confirmation"] = "operator"
        result["prepayment_amount"] = (
            int(result["amount"] * result["prepayment_percent"] / 100)
            if result["amount"] is not None and result["prepayment_percent"] is not None else None)
        if self.business.business_type == "venue_rental":
            result["deposit_policy"] = "Депозит назначает оператор аренды после согласования цены, максимум 20%"
        return result

    async def availability(self, args: AvailabilityArgs) -> dict:
        if (self.business.working_hours_start and self.business.working_hours_end
            and self.business.working_hours_end <= self.business.working_hours_start):
            raise HTTPException(422, "Для ночного графика используйте обычную форму записи или оператора")
        service = await self.service(args.service_id)
        today = datetime.now(ZoneInfo("Europe/Moscow")).date()
        if args.date < today or args.date > today + timedelta(days=366):
            raise HTTPException(422, "Выберите дату в течение ближайшего года")
        if service.is_additional:
            raise HTTPException(422, "Сначала выберите основную услугу")
        employees = ([await self.employee(args.employee_id, service)] if args.employee_id
                     else await self.specialists(service))
        slots = []
        for employee in employees:
            duration = args.duration_hours * 60 if args.duration_hours and self.business.business_type == "venue_rental" else service.duration_minutes
            if not await resource_works(self.db, employee, args.date, duration):
                continue
            if self.business.business_type == "venue_rental":
                if not employee.solo_price_per_hour or not args.duration_hours:
                    continue
                found = await rental.rental_slots(self.business.id, args.date, employee.id,
                                                 args.duration_hours, self.db)
                times = found["slots"]
            else:
                found = await client.get_slots(self.business.id, args.date, service.id, employee.id,
                    service.duration_minutes, False, None, self.db)
                times = [s.time for s in found if s.available]
            slots.extend({"time": t, "employee_id": employee.id, "employee_name": employee.name} for t in times)
        return {"date": args.date.isoformat(), "service_id": service.id, "slots": slots,
                "duration_hours_required": self.business.business_type == "venue_rental" and not args.duration_hours}

    async def prepare_booking(self, args: BookingArgs) -> dict:
        await self.require_tool("create_booking")
        service = await self.service(args.service_id)
        employee = await self.employee(args.employee_id, service)
        quote = await self.quote(PriceArgs.model_validate(args.model_dump()))
        if not quote["booking_supported"]:
            raise HTTPException(422, "Этот тариф оформляется через обычную форму записи или оператора")
        if self.business.business_type == "venue_rental":
            main = (await self.db.execute(select(Service.id).where(
                Service.business_id == self.business.id, Service.is_active.is_(True),
                Service.is_additional.is_(False)).order_by(Service.id).limit(1))).scalar_one_or_none()
            if main != service.id:
                raise HTTPException(422, "Для этого тарифа используйте форму записи")
        slots = await self.availability(AvailabilityArgs.model_validate({
            k: v for k, v in args.model_dump().items() if k in AvailabilityArgs.model_fields}))
        if not any(s["time"] == args.time and s["employee_id"] == args.employee_id for s in slots["slots"]):
            raise HTTPException(409, "Это время уже недоступно. Выберите другое окно")
        amount = f"{quote['amount']} ₽" if quote["amount"] is not None else "цену подтверждает менеджер"
        addon_names = [s.name for s in await self.addons(args.additional_service_ids)]
        description = (f"{self.business.name}: {service.name}, {employee.name}, "
                       f"{args.date.isoformat()} в {args.time}, {quote['duration_minutes']} мин, {amount}")
        if addon_names:
            description += ". Доп. услуги: " + ", ".join(addon_names)
        if quote["prepayment_percent"]:
            description += f". Предоплата: {quote['prepayment_percent']}%"
            description += ". Сообщите об отправке предоплаты в течение 10 минут после создания брони"
        if quote.get("deposit_policy"):
            description += ". " + quote["deposit_policy"]
        if quote["receipt_required"]:
            description += ". Для проверки предоплаты требуется чек на странице записи"
        return {"description": description, "args": args.model_dump(mode="json"), "quote": quote,
                "requires_contact": not self.user or (self.business.business_type == "venue_rental" and not self.user.phone),
                "requires_legal_consent": bool(self.business.legal_documents_enabled),
                "business_id": self.business.id, "cancellation_policy": self.business.cancellation_policy_text}

    async def execute_read(self, name: str, args: ToolArgs) -> dict:
        await self.require_tool(name)
        if name == "get_services":
            query = select(Service).where(Service.business_id == self.business.id, Service.is_active.is_(True))
            if args.query:
                # Search literal text, not user-supplied SQL LIKE wildcard patterns.
                escaped = args.query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                query = query.where(Service.name.ilike(f"%{escaped}%", escape="\\"))
            services = (await self.db.execute(query.order_by(Service.sort_order, Service.id).limit(50))).scalars().all()
            return {"services": [{"id": s.id, "name": s.name, "price": s.price if self.policy.show_prices else None,
                "duration_minutes": s.duration_minutes, "is_additional": s.is_additional,
                "description": (s.description or "")[:300]} for s in services]}
        if name == "get_service_details":
            data = self.service_data(await self.service(args.service_id))
            if not self.policy.show_prices:
                for key in ("price", "tariff_description"):
                    data.pop(key, None)
            return data
        if name == "get_prices":
            return await self.quote(args)
        if name == "get_specialists":
            return {"specialists": [{"id": e.id, "name": e.name, "specialization": e.specialization,
                "description": e.description, "instructions": e.ai_instruction,
                "capacity": e.capacity} for e in await self.specialists(await self.service(args.service_id))]}
        if name == "check_availability":
            return await self.availability(args)
        if name == "get_my_bookings":
            if not self.user:
                return {"error": "Для просмотра личных записей войдите в ServGo"}
            rows = (await self.db.execute(select(Booking).where(
                Booking.business_id == self.business.id, Booking.client_id == self.user.id,
                Booking.booking_date >= Date.today()).order_by(Booking.booking_date, Booking.booking_time)
                .limit(10))).scalars().all()
            return {"bookings": [{"id": b.id, "date": str(b.booking_date),
                "time": b.booking_time.strftime("%H:%M"), "status": b.status,
                "manage_url": (f"/rental/b/{b.notify_token}" if b.duration_minutes is not None
                    else f"/b/{b.notify_token}") if b.notify_token else "/my"} for b in rows]}
        raise HTTPException(422, "Неизвестный инструмент")

    async def book(self, prepared: dict, confirmation) -> tuple[list[int], str | None]:
        args = BookingArgs.model_validate(prepared["args"])
        await lock_resource_days(self.db, args.employee_id, [args.date])
        fresh = await self.prepare_booking(args)
        if fresh["quote"] != prepared["quote"] or fresh["description"] != prepared["description"]:
            raise HTTPException(409, "Условия записи изменились. Запросите новую карточку подтверждения")
        name = self.user.full_name if self.user else confirmation.client_name
        phone = self.user.phone if self.user and self.user.phone else confirmation.client_phone
        if fresh["requires_contact"] and (not name or not phone):
            raise HTTPException(422, "Укажите имя и телефон в форме подтверждения")
        if phone:
            digits = "".join(c for c in phone if c.isdigit())
            if not 10 <= len(digits) <= 15:
                raise HTTPException(422, "Укажите корректный телефон")
            phone = "+" + digits
        if fresh["requires_legal_consent"] and not (
            confirmation.personal_data_consent and confirmation.booking_terms_accepted):
            raise HTTPException(422, "Отдельно подтвердите согласие на обработку данных и условия записи")
        if self.business.business_type == "venue_rental":
            # RentalRequest has no legal-consent fields yet; do not bypass the business policy.
            if fresh["requires_legal_consent"]:
                raise HTTPException(422, "Для аренды с юридическими условиями используйте форму записи")
            result = await rental.create_rental_request(self.business.id, rental.RentalRequest(
                date=args.date, time=args.time, employee_id=args.employee_id,
                duration_hours=args.duration_hours, client_name=name, client_phone=phone,
                additional_service_ids=args.additional_service_ids), self.db, user=self.user, commit=False)
            return [result["id"]], f"/rental/b/{result['tracking_token']}"
        body = CreateBookingIn(business_id=self.business.id, service_id=args.service_id,
            employee_id=args.employee_id, date=args.date, time=args.time,
            additional_service_ids=args.additional_service_ids, client_name=name, client_phone=phone,
            personal_data_consent=confirmation.personal_data_consent,
            booking_terms_accepted=confirmation.booking_terms_accepted)
        # Guest creation in the existing CRUD helper commits. Flush our guest here instead
        # so the booking and confirmation result remain one atomic transaction.
        user = self.user
        if user is None:
            import secrets
            from database.models import User
            user = User(telegram_id=-secrets.randbelow(2**60)-1, full_name=name, phone=phone)
            self.db.add(user)
            await self.db.flush()
        result = await client.create_booking_visit(body, self.db, user, commit=False)
        ids = [b.id for b in result]
        booking = await self.db.get(Booking, ids[0])
        return ids, f"/b/{booking.notify_token}" if booking.notify_token else None
