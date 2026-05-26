"""
Главный файл бота
Точка входа для запуска
"""
import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_TOKEN
from bot.handlers import common, client, admin, master, admin_management
from database import init_db
from bot.services.scheduler import ReminderScheduler


# Настройка логирования в файл
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_debug.log', encoding='utf-8', mode='w'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Отключаем спам от aiogram и aiohttp
logging.getLogger('aiogram').setLevel(logging.INFO)
logging.getLogger('aiohttp').setLevel(logging.WARNING)


class CallbackLoggingMiddleware(BaseMiddleware):
    """Middleware для логирования callback_query"""

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        logger.info(f"=== CALLBACK === data: {event.data}, user: {event.from_user.id}")
        state = data.get("state")
        if state:
            current_state = await state.get_state()
            logger.info(f"=== STATE === {current_state}")

        try:
            result = await handler(event, data)
            logger.info(f"=== CALLBACK OK ===")
            return result
        except Exception as e:
            logger.error(f"=== CALLBACK ERROR === {e}", exc_info=True)
            raise


class MessageLoggingMiddleware(BaseMiddleware):
    """Middleware для логирования message"""

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        logger.info(f"=== MESSAGE === text: {event.text}, user: {event.from_user.id}")

        try:
            result = await handler(event, data)
            logger.info(f"=== MESSAGE OK ===")
            return result
        except Exception as e:
            logger.error(f"=== MESSAGE ERROR === {e}", exc_info=True)
            raise


async def main():
    """Основная функция запуска бота"""
    logger.info("Запуск бота...")

    # Инициализация бота и диспетчера
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Добавляем middleware для логирования
    dp.callback_query.middleware(CallbackLoggingMiddleware())
    dp.message.middleware(MessageLoggingMiddleware())

    # Регистрация роутеров (порядок важен!)
    dp.include_router(common.router)
    dp.include_router(admin_management.router)
    dp.include_router(master.router)
    dp.include_router(client.router)
    dp.include_router(admin.router)

    # Инициализация базы данных
    logger.info("Инициализация базы данных...")
    await init_db()
    logger.info("База данных готова")

    # Запуск планировщика уведомлений
    scheduler = ReminderScheduler(bot)
    scheduler.start()
    logger.info("Планировщик уведомлений запущен")

    # Запуск бота
    logger.info("Бот запущен и готов к работе!")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
