import asyncio
import logging
import sys
import signal
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from config.settings import Settings
from services.retailcrm_service import RetailCRMService
from services.order_monitor_service import OrderMonitorService
from services.rate_limiter import get_rate_limiter  # ← ДОБАВЛЕНО
from middlewares.auth_middleware import AuthMiddleware

# Импорт handlers
from handlers import start_handler
from handlers import order_handler
from handlers import status_handler
from handlers import order_callback_handler
from handlers import stats_handler
from handlers import get_chat_id_handler

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)

logger = logging.getLogger(__name__)

# Глобальные переменные для graceful shutdown
order_monitor = None
dp = None
bot = None
rate_limiter = None  # ← ДОБАВЛЕНО


def signal_handler(signum, frame):
    """Обработчик сигналов для graceful shutdown"""
    logger.info(f"Получен сигнал {signum}, начинаю остановку бота...")
    sys.exit(0)


async def main():
    """Главная функция запуска бота"""
    global order_monitor, dp, bot, rate_limiter  # ← ДОБАВЛЕНО rate_limiter
    
    try:
        logger.info("="*60)
        logger.info("🚀 Запуск Telegram бота для RetailCRM")
        logger.info("="*60)
        
        # Получаем настройки
        bot_token = Settings.get_bot_token()
        retailcrm_api_key = Settings.get_retailcrm_api_key()
        retailcrm_domain = Settings.get_retailcrm_domain()
        admin_config = Settings.get_admin_full_config()
        
        if not admin_config or len(admin_config) == 0:
            logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: Нет настроенных администраторов в ADMIN_WAREHOUSES!")
            logger.error("Бот не может работать без администраторов. Проверьте переменную окружения ADMIN_WAREHOUSES")
            sys.exit(1)
        
        logger.info(f"📦 RetailCRM Domain: {retailcrm_domain}")
        logger.info(f"👥 Администраторов: {len(admin_config)}")
        
        # ============ ИНИЦИАЛИЗАЦИЯ REDIS RATE LIMITER ============
        try:
            rate_limiter = get_rate_limiter(
                host=Settings.get_redis_host(),
                port=Settings.get_redis_port(),
                db=Settings.get_redis_db()
            )
            logger.info("✅ Redis Rate Limiter инициализирован")
        except Exception as e:
            logger.warning(f"⚠️ Redis недоступен: {e}")
            logger.warning("⚠️ Rate limiting будет работать в FALLBACK режиме")
        
        # Инициализация бота
        bot = Bot(
            token=bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        
        # Инициализация dispatcher
        dp = Dispatcher()
        
        # Инициализация сервисов
        retailcrm_service = RetailCRMService(
            api_key=retailcrm_api_key,
            domain=retailcrm_domain
        )
        
        # Инициализация middleware для авторизации
        auth_middleware = AuthMiddleware(list(admin_config.keys()))
        dp.message.middleware(auth_middleware)
        dp.callback_query.middleware(auth_middleware)
        logger.info("✅ Middleware авторизации установлен")
        
        # Регистрация handlers напрямую в dispatcher
        dp.include_router(start_handler.router)
        dp.include_router(order_handler.router)
        dp.include_router(status_handler.router)
        dp.include_router(order_callback_handler.router)
        dp.include_router(stats_handler.router)
        dp.include_router(get_chat_id_handler.router)
        logger.info("✅ Handlers зарегистрированы")
        
        # Инициализация сервиса мониторинга заказов
        order_monitor = OrderMonitorService(
            bot=bot,
            retailcrm_service=retailcrm_service,
            admin_config=admin_config
        )
        logger.info("✅ OrderMonitorService инициализирован")
        
        # Запуск мониторинга в фоновом режиме
        await order_monitor.start()
        logger.info("✅ Мониторинг заказов запущен")
        
        # Отправка тестового сообщения
        try:
            me = await bot.get_me()
            logger.info(f"✅ Бот запущен: @{me.username} (ID: {me.id})")
        except Exception as e:
            logger.error(f"❌ Ошибка при получении информации о боте: {e}")
        
        logger.info("="*60)
        logger.info("🟢 Бот готов к работе!")
        logger.info("📡 Polling запущен...")
        logger.info("="*60)
        
        # Запуск polling
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    
    except KeyboardInterrupt:
        logger.info("⏸️ Получен сигнал остановки (Ctrl+C)")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при запуске: {e}", exc_info=True)
    finally:
        # Graceful shutdown
        logger.info("🛑 Остановка бота...")
        
        try:
            if order_monitor and order_monitor.is_running:
                await order_monitor.stop()
                logger.info("✅ Мониторинг остановлен")
        except Exception as e:
            logger.error(f"Ошибка при остановке мониторинга: {e}")
        
        try:
            if bot:
                await bot.session.close()
                logger.info("✅ Сессия бота закрыта")
        except Exception as e:
            logger.error(f"Ошибка при закрытии сессии: {e}")
        
        logger.info("="*60)
        logger.info("👋 Бот полностью остановлен")
        logger.info("="*60)


if __name__ == "__main__":
    # Регистрация обработчиков сигналов для graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("✅ Бот завершил работу штатно")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
