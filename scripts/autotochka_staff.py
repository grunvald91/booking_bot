"""Авто точка (business 16): выходные мастеров и услуги — чтение / запись.

По умолчанию только читает и печатает состояние (без личных данных клиентов).
Запускается на боевом сервере в окружении приложения.
"""
import argparse
import asyncio
import json
from datetime import date, timedelta

BUSINESS_ID = 16

# Выходные на две недели вперёд (включительно): день недели 0=Пн … 6=Вс
PERIOD_START = date(2026, 10, 27)
PERIOD_END = date(2026, 11, 9)
DAYS_OFF = {
    'Илья': {3, 4},       # чт, пт
    'Алексей': {1},       # вт
    'Сослан': {5},        # сб
    'Дмитрий': {6, 0},    # вс, пн
    'Павел': {6},         # вс
}
EXPECTED_IDS = {'Сослан': 49, 'Илья': 50, 'Алексей': 51, 'Дмитрий': 52, 'Павел': 53}
# Существующие услуги, которые добавляем Алексею: сход-развал обычных легковых (перед; перед + зад)
ALEXEY_EXISTING_SERVICES = {83: 'Сход-развал: легковой, перед', 84: 'Сход-развал: легковой, перед + зад'}
# Новые услуги: имя -> id мастеров
NEW_SERVICES = {
    'Диагностика двигателя': [50],      # Илья
    'Диагностика ходовой': [50, 51],    # Илья и Алексей
}
NEW_PRICE = 1000
NEW_MINUTES = 30


async def run(apply: bool) -> None:
    from sqlalchemy import select
    from database.database import async_session_maker
    from database.models import Business, Employee, EmployeeDayOff, EmployeeService, Service

    async with async_session_maker() as db:
        business = await db.get(Business, BUSINESS_ID)
        if not business:
            raise RuntimeError('Business 16 not found')
        print(f'business={business.id}; name={business.name}; type={business.business_type}; '
              f'hours={business.working_hours_start}-{business.working_hours_end}; interval={business.booking_interval_minutes}')
        employees = (await db.execute(select(Employee).where(Employee.business_id == BUSINESS_ID).order_by(Employee.id))).scalars().all()
        services = (await db.execute(select(Service).where(Service.business_id == BUSINESS_ID).order_by(Service.sort_order, Service.id))).scalars().all()
        links = (await db.execute(select(EmployeeService.employee_id, EmployeeService.service_id)
                                  .join(Employee, Employee.id == EmployeeService.employee_id)
                                  .where(Employee.business_id == BUSINESS_ID))).all()
        by_emp = {}
        for e_id, s_id in links:
            by_emp.setdefault(e_id, set()).add(s_id)
        print('--- employees')
        for e in employees:
            print(f'emp id={e.id}; name={e.name!r}; role={e.role}; active={e.is_active}; spec={e.specialization!r}; '
                  f'interval={e.booking_interval_minutes}; service_links={sorted(by_emp.get(e.id, []))}')
        print('--- services')
        for s in services:
            print(f'svc id={s.id}; name={s.name!r}; price={s.price}; min={s.duration_minutes}; active={s.is_active}; '
                  f'additional={s.is_additional}; sort={s.sort_order}; allowed_emp={s.available_employee_ids}')
        today = date.today()
        offs = (await db.execute(select(EmployeeDayOff).join(Employee, Employee.id == EmployeeDayOff.employee_id)
                                 .where(Employee.business_id == BUSINESS_ID, EmployeeDayOff.date >= today)
                                 .order_by(EmployeeDayOff.employee_id, EmployeeDayOff.date))).scalars().all()
        print(f'--- days_off_from_today={today}; count={len(offs)}')
        for o in offs:
            print(f'off emp={o.employee_id}; date={o.date}; reason={o.reason!r}')
        if not apply:
            return

        # ── Проверки перед записью ──
        emp_by_name = {e.name: e for e in employees}
        for name, eid in EXPECTED_IDS.items():
            if name not in emp_by_name or emp_by_name[name].id != eid:
                raise RuntimeError(f'Employee {name} does not match expected id {eid}')
        svc_by_id = {sv.id: sv for sv in services}
        for sid, sname in ALEXEY_EXISTING_SERVICES.items():
            if sid not in svc_by_id or svc_by_id[sid].name != sname:
                raise RuntimeError(f'Service {sid} does not match {sname!r}')
        existing_names = {sv.name: sv for sv in services}

        # ── 1. Выходные ──
        from database.models import Booking
        existing_off = {(o.employee_id, o.date) for o in offs}
        # offs печатались только с сегодняшнего дня; границы периода начинаются сегодня
        planned = []
        d = PERIOD_START
        while d <= PERIOD_END:
            for name, weekdays in DAYS_OFF.items():
                if d.weekday() in weekdays and (emp_by_name[name].id, d) not in existing_off:
                    planned.append((emp_by_name[name], d))
            d += timedelta(days=1)
        conflicts = []
        for emp, day in planned:
            rows = (await db.execute(select(Booking.id).where(
                Booking.employee_id == emp.id, Booking.booking_date == day,
                Booking.status.notin_(['cancelled', 'rejected'])))).all()
            if rows:
                conflicts.append(f'{emp.name} {day}: bookings={len(rows)}')
        if conflicts:
            raise RuntimeError('Refusing: planned days off clash with existing bookings: ' + '; '.join(conflicts))
        for emp, day in planned:
            db.add(EmployeeDayOff(employee_id=emp.id, date=day, reason='Выходной'))

        # ── 2. Новые услуги ──
        next_sort = max([sv.sort_order or 0 for sv in services] + [-1]) + 1
        created = []
        for name, emp_ids in NEW_SERVICES.items():
            svc = existing_names.get(name)
            if svc is None:
                svc = Service(business_id=BUSINESS_ID, name=name, duration_minutes=NEW_MINUTES, price=NEW_PRICE,
                              is_active=True, is_additional=False, is_hourly_price=False, sort_order=next_sort)
                next_sort += 1
                db.add(svc)
                await db.flush()
                created.append(name)
            else:
                svc.duration_minutes = NEW_MINUTES
                svc.price = NEW_PRICE
                svc.is_active = True
            svc.available_employee_ids = json.dumps(sorted(emp_ids))
            for eid in emp_ids:
                have = (await db.execute(select(EmployeeService).where(
                    EmployeeService.employee_id == eid, EmployeeService.service_id == svc.id))).scalar_one_or_none()
                if have is None:
                    db.add(EmployeeService(employee_id=eid, service_id=svc.id))

        # ── 3. Алексей + сход-развал обычных легковых ──
        alexey = emp_by_name['Алексей']
        for sid in ALEXEY_EXISTING_SERVICES:
            svc = svc_by_id[sid]
            allowed = set(json.loads(svc.available_employee_ids)) if svc.available_employee_ids else set()
            allowed.add(alexey.id)
            svc.available_employee_ids = json.dumps(sorted(allowed))
            have = (await db.execute(select(EmployeeService).where(
                EmployeeService.employee_id == alexey.id, EmployeeService.service_id == sid))).scalar_one_or_none()
            if have is None:
                db.add(EmployeeService(employee_id=alexey.id, service_id=sid))
        await db.commit()
        print(f'APPLIED: days_off_added={len(planned)}; services_created={created}; alexey_services={sorted(ALEXEY_EXISTING_SERVICES)}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    asyncio.run(run(parser.parse_args().apply))
