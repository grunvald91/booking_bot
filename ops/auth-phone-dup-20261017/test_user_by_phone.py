"""Offline check of the duplicate-phone lookup used by /auth/phone and /auth/verify."""
import asyncio
from typing import Optional

from sqlalchemy import BigInteger, Column, Integer, String, case, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger)
    phone = Column(String)


async def _user_by_phone(db: AsyncSession, phone: str) -> Optional[User]:
    result = await db.execute(
        select(User)
        .where(User.phone == phone)
        .order_by(case((User.telegram_id > 0, 0), else_=1), User.id)
        .limit(1)
    )
    return result.scalars().first()


async def main():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine)
    async with Session() as db:
        db.add_all([
            User(id=1, telegram_id=-1700000, phone="+79990000001"),  # web-only duplicate, older
            User(id=2, telegram_id=555, phone="+79990000001"),       # real Telegram account
            User(id=3, telegram_id=777, phone="+79990000001"),       # newer Telegram duplicate
            User(id=4, telegram_id=-5, phone="+79990000002"),
            User(id=5, telegram_id=-6, phone="+79990000002"),
            User(id=6, telegram_id=888, phone="+79990000003"),
        ])
        await db.commit()
        assert (await _user_by_phone(db, "+79990000001")).id == 2
        assert (await _user_by_phone(db, "+79990000002")).id == 4
        assert (await _user_by_phone(db, "+79990000003")).id == 6
        assert await _user_by_phone(db, "+70000000000") is None
    print("user_by_phone: all checks passed")


asyncio.run(main())
