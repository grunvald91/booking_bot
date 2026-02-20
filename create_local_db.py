"""
Скрипт для создания локальной базы данных для разработки
"""
import asyncio
import asyncpg


async def create_database():
    """Создание базы данных booking_bot_dev"""
    try:
        # Подключаемся к postgres базе для создания новой БД
        conn = await asyncpg.connect(
            host='localhost',
            port=5432,
            user='postgres',
            password='Booking2025',
            database='postgres'
        )

        # Проверяем существует ли база
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'booking_bot_dev'"
        )

        if exists:
            print("База данных 'booking_bot_dev' уже существует")
        else:
            # Создаем базу данных
            await conn.execute('CREATE DATABASE booking_bot_dev')
            print("База данных 'booking_bot_dev' успешно создана!")

        await conn.close()

    except Exception as e:
        print(f"Ошибка при создании базы данных: {e}")
        print("\nПроверьте:")
        print("1. PostgreSQL запущен")
        print("2. Пароль в .env файле правильный")
        print("3. Пользователь postgres существует")


if __name__ == "__main__":
    asyncio.run(create_database())
