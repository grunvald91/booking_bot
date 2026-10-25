"""Configure the existing business 16 «Авто точка»: staff days off, new employee, wheel-alignment price list.

Data only: no code deploy, no restarts, no deletes. Read-only by default; --apply
  * adds days off for the next two weeks (start date below, 14 days);
  * adds the employee Павел (запчасти) with no services and Sunday off;
  * turns service 83 «Сход-развал» into the first price variant and adds the other variants;
  * links every variant to Сослан only (nobody else does alignment);
  * clears the booking step names that were filled with names by mistake ('Сослан', 'Сход-развал').
Safe to run twice: everything is matched by name/date and updated in place.
Run on the production host with its existing Python environment/database config.
"""
import argparse
import asyncio
import json
from datetime import date, timedelta

BUSINESS_ID = 16
BUSINESS_NAME = 'Авто точка'
START_DATE = date(2026, 10, 25)
DAYS = 14
MASTER_ID = 49  # Сослан: the only one who does alignment
EXISTING_SERVICE_ID = 83

# weekday numbers: Monday=0 … Sunday=6
OFF_WEEKDAYS = {
    'Илья': (3, 4),      # четверг, пятница
    'Алексей': (1,),     # вторник
    'Сослан': (5,),      # суббота
    'Дмитрий': (6, 0),   # воскресенье, понедельник
    'Павел': (6,),       # воскресенье
}
EXPECTED_EMPLOYEES = {'Сослан': 49, 'Илья': 50, 'Алексей': 51, 'Дмитрий': 52}

DURATION_MINUTES = 60  # same as the existing «Сход-развал»; the owner did not give a different time

# (name, price, description). Order = sort_order. The first sentence is what the client sees in the list.
SERVICES = [
    ('Сход-развал: легковой, перед', 1700,
     'Седан, хэтчбек, кроссовер на обычных пружинах. Настраиваем передние колёса.'),
    ('Сход-развал: легковой, перед + зад', 2500,
     'Тот же обычный автомобиль, но настраиваем все четыре колеса (передние и задние).'),
    ('Сход-развал: пневмоподвеска, перед', 2500,
     'Для машин с пневмоподвеской: вместо пружин воздушные баллоны, кузов можно поднимать и опускать '
     'кнопкой или в меню. Любая марка, в том числе Mercedes. Настраиваем передние колёса.'),
    ('Сход-развал: пневмоподвеска, перед + зад', 3500,
     'Для машин с пневмоподвеской (воздушные баллоны вместо пружин, высота кузова меняется). '
     'Любая марка, в том числе Mercedes. Настраиваем все четыре колеса.'),
    ('Сход-развал: Mercedes / BMW, перед', 2000,
     'Mercedes и BMW на обычных пружинах, без пневмоподвески. Настраиваем передние колёса.'),
    ('Сход-развал: Mercedes / BMW, перед + зад', 3000,
     'Mercedes и BMW на обычных пружинах, без пневмоподвески. Настраиваем все четыре колеса.'),
    ('Сход-развал: рамный внедорожник, перед', 2500,
     'Внедорожник с отдельной стальной рамой под кузовом, например Land Cruiser, Prado, Pajero, '
     'УАЗ Патриот. Настраиваем передние колёса.'),
    ('Сход-развал: большой пикап (Tundra, RAM, Raptor)', 5000,
     'Крупные американские пикапы: Toyota Tundra, RAM, Ford Raptor (F-150) и похожие по размеру. '
     'Цена за услугу одна.'),
]
GENERIC_NOTE = ' Не уверены, какой вариант выбрать — позвоните нам: +7 918 980-15-08.'


def plan_days_off(start: date = START_DATE, days: int = DAYS) -> dict:
    """{employee name: [date, …]} for the first `days` days starting at `start`."""
    result = {}
    for name, weekdays in OFF_WEEKDAYS.items():
        result[name] = [start + timedelta(days=i) for i in range(days)
                        if (start + timedelta(days=i)).weekday() in weekdays]
    return result


def service_description(text: str) -> str:
    return text + GENERIC_NOTE


async def configure(apply: bool) -> None:
    from sqlalchemy import select, func
    from database.database import async_session_maker
    from database.booking_safety import ACTIVE_BOOKING_STATUSES
    from database.models import Booking, Business, Employee, EmployeeDayOff, EmployeeService, Service

    async with async_session_maker() as db:
        business = await db.get(Business, BUSINESS_ID)
        if not business or business.name != BUSINESS_NAME:
            raise RuntimeError('Business 16 «Авто точка» not found; refusing to change anything')
        employees = (await db.execute(select(Employee).where(Employee.business_id == BUSINESS_ID))).scalars().all()
        by_name = {e.name: e for e in employees}
        for name, emp_id in EXPECTED_EMPLOYEES.items():
            if name not in by_name or by_name[name].id != emp_id:
                raise RuntimeError(f'Employee {name} (id {emp_id}) differs from what was agreed; stopping')
        services = (await db.execute(select(Service).where(Service.business_id == BUSINESS_ID))).scalars().all()
        base = next((s for s in services if s.id == EXISTING_SERVICE_ID), None)
        if not base:
            raise RuntimeError('Service 83 not found; stopping')
        by_service_name = {s.name: s for s in services}

        try:
            labels = json.loads(business.booking_labels) if business.booking_labels else {}
        except (TypeError, ValueError):
            labels = {}
        plan = plan_days_off()
        existing_off = {(row.employee_id, row.date) for row in (await db.execute(
            select(EmployeeDayOff).where(EmployeeDayOff.employee_id.in_([e.id for e in employees])))).scalars().all()}

        # Existing bookings that fall on the new days off (only counted, never touched or printed).
        conflicts = 0
        for name, dates in plan.items():
            emp = by_name.get(name)
            if emp is None or not dates:
                continue
            conflicts += (await db.execute(select(func.count()).select_from(Booking).where(
                Booking.employee_id == emp.id, Booking.booking_date.in_(dates),
                Booking.status.in_(ACTIVE_BOOKING_STATUSES)))).scalar_one()

        print(f'preflight_business_id={BUSINESS_ID}; employees={len(employees)}; services={len(services)}; '
              f'apply={apply}')
        print(f'before: service83=({base.name!r}, price={base.price}, minutes={base.duration_minutes}, '
              f'active={base.is_active}); booking_labels={labels}')
        for name, dates in plan.items():
            print(f'days_off {name}: {", ".join(d.strftime("%d.%m") for d in dates)}')
        print(f'active_bookings_on_new_days_off={conflicts}')
        for index, (name, price, _) in enumerate(SERVICES, start=1):
            print(f'service {index}: {name} = {price} RUB ({"exists" if name in by_service_name or index == 1 else "new"})')
        if not apply:
            return

        # 1. Employee Павел (no services)
        pavel = by_name.get('Павел')
        if pavel is None:
            pavel = Employee(business_id=BUSINESS_ID, name='Павел', specialization='Запчасти',
                             role='master', is_active=True)
            db.add(pavel)
            await db.flush()
            by_name['Павел'] = pavel

        # 2. Days off
        added_off = 0
        for name, dates in plan.items():
            emp = by_name[name]
            for d in dates:
                if (emp.id, d) not in existing_off:
                    db.add(EmployeeDayOff(employee_id=emp.id, date=d, reason='Выходной'))
                    added_off += 1

        # 3. Services: variant 1 reuses service 83 (keeps its booking history), the rest are created
        master_ids = json.dumps([MASTER_ID])
        service_rows = []
        for index, (name, price, text) in enumerate(SERVICES, start=1):
            row = base if index == 1 else by_service_name.get(name)
            if row is None:
                row = Service(business_id=BUSINESS_ID, name=name, duration_minutes=DURATION_MINUTES,
                              is_active=True, is_additional=False, pricing_type='fixed')
                db.add(row)
            row.name = name
            row.price = price
            row.description = service_description(text)
            row.duration_minutes = row.duration_minutes or DURATION_MINUTES
            row.is_active = True
            row.sort_order = index
            row.available_employee_ids = master_ids
            service_rows.append(row)
        await db.flush()

        # 4. Only Сослан does these services
        linked = 0
        for row in service_rows:
            exists = (await db.execute(select(EmployeeService).where(
                EmployeeService.employee_id == MASTER_ID, EmployeeService.service_id == row.id))).scalar_one_or_none()
            if exists is None:
                db.add(EmployeeService(employee_id=MASTER_ID, service_id=row.id))
                linked += 1

        # 5. Step names were filled with a master's / service's name by mistake: back to the standard names
        for key in ('resource', 'service'):
            labels.pop(key, None)
        business.booking_labels = json.dumps(labels, ensure_ascii=False) if labels else None

        await db.commit()
        print(f'applied: days_off_added={added_off}; services_total={len(service_rows)}; '
              f'links_added={linked}; employee_pavel_id={pavel.id}; labels_after={labels}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Write the changes to business 16')
    args = parser.parse_args()
    asyncio.run(configure(args.apply))
