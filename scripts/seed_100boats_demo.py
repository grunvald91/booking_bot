"""Seed an isolated, inactive 100boats showcase in the existing ServGo database.

No public availability, deposits, bookings, or payment confirmations are created.
The live generic booking flow cannot safely price short rentals or reserve intervals.
Run on the ServGo host from /opt/booking_bot with ./venv/bin/python.
"""
import asyncio

from sqlalchemy import select
from database.database import async_session_maker
from database.models import Business, BusinessOwner, Employee, EmployeeService, Service, User

NAME = '100boats — демонстрация ServGo'
OWNER_USERNAME = 'Grunvald'
DISCLAIMER = 'Демонстрационный прототип ServGo на основе публичной информации. Не является официальным сервисом 100boats.'
CONDITIONS = (
    'Публичные почасовые цены указаны для аренды от 5 часов. При аренде 1–4 часа '
    'точную стоимость подтверждает менеджер; стоимость суток рассчитывается индивидуально. '
    'Рекомендуемая обычная прогулка — 3–4 часа. Свободное время в демонстрации '
    'условное и не отражает реальную занятость судов 100boats.'
)
VESSELS = [
    ('Princess 45', 'Моторная яхта VIP', 19000, 3, 6, '14 м', '4,27 м', 'Великобритания', '61 км/ч', None,
     'Двухпалубная моторная яхта VIP-класса с флайбриджем.'),
    ('Fairline Squadron 58', 'Моторная яхта Luxury', 39000, 3, 6, '19 м', '5 м', 'Великобритания', '60 км/ч', None,
     'Большая моторная яхта с флайбриджем и просторной развлекательной зоной. Возможна установка гидроциклов.'),
    ('Azimut 39', 'Моторная яхта', 16000, 2, 6, '11 м', '4 м', 'Италия', '55 км/ч', None,
     'Моторная яхта с флайбриджем для семейного отдыха, праздников, вечеринок и рыбалки.'),
    ('Sunseeker 72', 'VIP-моторная яхта', 59000, 4, 8, '25 м', '6 м', 'Великобритания', '75 км/ч', None,
     'Одна из крупнейших яхт каталога, со стабилизатором качки, просторным салоном, каютами и водным бассейном.'),
    ('Princess 56', 'Премиум-моторная яхта', 29000, 4, 8, '19 м', '5 м', 'Великобритания', '55 км/ч', 11,
     'Большая премиум-яхта с флайбриджем, просторным салоном и зонами для отдыха и загара.'),
    ('Fazerint 42', 'Моторная яхта', 13500, 3, 6, '13 м', '3 м', 'Россия', '50 км/ч', None,
     'Скоростная яхта для небольшой компании или семейной прогулки. Выход из Имеретинской марины.'),
    ('Lavezzi 40', 'Парусный катамаран', 16000, 4, 6, '13 м', '6 м', 'Италия', '20 км/ч', None,
     'Просторный катамаран с большой площадью палубы, сетками для отдыха над водой и парусным форматом.'),
    ('Dufour Atoll 43', 'Парусная яхта', 12000, 2, 6, '13 м', '4,65 м', 'Франция', '10 км/ч', 12,
     'Парусная яхта, рассчитанная на чартер, с зонами отдыха, акустической системой и панорамной крышей.'),
    ('Bavaria 380 Sport', 'Моторный катер', 12000, 2, 6, '12 м', '4 м', 'Германия', '65 км/ч', 11,
     'Скоростной катер для морских прогулок. Капитан и топливо входят в стоимость.'),
]

async def main():
    async with async_session_maker() as db:
        owner = (await db.execute(select(User).where(User.username == OWNER_USERNAME))).scalar_one()
        existing = (await db.execute(select(Business.id).where(Business.name == NAME))).scalar_one_or_none()
        if existing is not None:
            print(f'existing_demo_business_id={existing}; no changes')
            return
        business = Business(
            owner_id=owner.id, name=NAME, business_type='venue_rental',
            description='Аренда моторных и парусных яхт и катеров в Сочи и Имеретинке. Почасовая, дневная и длительная аренда. После бронирования капитан подтверждает время и место встречи в порту.\n\n'+DISCLAIMER+'\n'+CONDITIONS,
            address='Россия, Краснодарский край, Сочи, ул. Несебрская, 6, 354340',
            phone='+7 (995) 00-599-01',
            directions='Офис: ул. Несебрская, 6. Горячая линия WhatsApp — 24/7; часы выхода судов не опубликованы, время и порт подтверждаются после бронирования.',
            booking_interval_minutes=60, working_hours_start=None, working_hours_end=None,
            prepayment_enabled=False, prepayment_percent=None,
            payment_details='Размер предоплаты — до 20%, сумма подтверждается менеджером. Сбербанк Онлайн либо счёт для юридического лица. Остаток — до начала аренды наличными или через Сбербанк Онлайн. Для юридических лиц при длительной аренде возможна 100% предоплата по договору.',
            cancellation_policy_text='Отмена за 7 дней — без удержаний; при неявке предоплата не возвращается. При небезопасной погоде или закрытом порте предлагается перенос; если клиент не хочет переносить из-за погоды, деньги возвращаются.',
            is_active=False,
        )
        db.add(business)
        await db.flush()
        db.add(BusinessOwner(business_id=business.id, user_id=owner.id, role='owner', added_by_id=owner.id))
        service = Service(
            business_id=business.id, name='Аренда яхты / катера', duration_minutes=60,
            price=None, is_active=True, is_additional=False, is_hourly_price=False,
            tariff_description=CONDITIONS, sort_order=0,
        )
        db.add(service)
        await db.flush()
        for name, kind, rate, cabins, beds, length, width, country, speed, capacity, description in VESSELS:
            vessel = Employee(
                business_id=business.id, name=name, role='master', is_active=True,
                specialization=kind, booking_interval_minutes=60, capacity=capacity,
                description=(f'{description}\nКаюты: {cabins}; спальных мест: {beds}; длина: {length}; ширина: {width}; '
                             f'страна: {country}; максимальная скорость: {speed}. '
                             f'Опубликовано от {rate:,} ₽/час при аренде от 5 часов. {CONDITIONS}'),
                min_booking_minutes=60, solo_price_per_hour=None,
            )
            db.add(vessel)
            await db.flush()
            db.add(EmployeeService(employee_id=vessel.id, service_id=service.id))
        addons = [
            ('Фотосессия / видеоролик на яхте', 15000, 'Профессиональная фото- или видеосъёмка; заявлены от 15 фотографий большого разрешения, версии для соцсетей и видеоролик.'),
            ('Премиальный трансфер из отеля', 5000, 'Mercedes-Maybach, Mercedes S-Class, Mercedes V-Class до 7 мест.'),
            ('Спорткар / кабриолет', None, 'От 25 000 ₽. Индивидуальная цена требует подтверждения менеджером.'),
            ('Вертолётная прогулка / трансфер', None, 'От 25 000 ₽. Robinson R44, до 3 пассажиров. Индивидуальная цена требует подтверждения.'),
        ]
        for index, (name, price, description) in enumerate(addons, 1):
            db.add(Service(business_id=business.id, name=name, description=description,
                           duration_minutes=0, price=price, is_active=True,
                           is_additional=True, is_hourly_price=False, sort_order=index))
        await db.commit()
        print(f'created_demo_business_id={business.id}; owner_id={owner.id}; vessels={len(VESSELS)}; addons={len(addons)}; active={business.is_active}')

if __name__ == '__main__':
    asyncio.run(main())
