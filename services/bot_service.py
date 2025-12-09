from aiogram import Bot, Dispatcher
from services.order_monitor_service import OrderMonitorService
from services.retailcrm_service import RetailCRMService
from middlewares.auth_middleware import AuthMiddleware
from config.settings import Settings


class BotService:
    """Сервис для управления ботом и диспетчером"""
    
    def __init__(self, token: str):
        self.bot = Bot(token=token)
        self.dispatcher = Dispatcher()
        self.monitor_service = None
    
    def setup_auth_middleware(self, allowed_chat_ids: list):
        """Настраивает middleware для проверки доступа"""
        auth_middleware = AuthMiddleware(allowed_chat_ids)
        self.dispatcher.message.middleware(auth_middleware)
        self.dispatcher.callback_query.middleware(auth_middleware)
    
    def register_router(self, router):
        """Регистрирует роутер в диспетчере"""
        self.dispatcher.include_router(router)
    
    def setup_monitoring(self):
        """Настраивает сервис мониторинга заказов"""
        retailcrm_service = RetailCRMService(
            api_key=Settings.get_retailcrm_api_key(),
            domain=Settings.get_retailcrm_domain()
        )
        
        admin_warehouses = Settings.get_admin_warehouses()
        
        self.monitor_service = OrderMonitorService(
            bot=self.bot,
            retailcrm_service=retailcrm_service,
            admin_warehouses=admin_warehouses
        )
    
    async def on_startup(self, *args, **kwargs):
        """Действия при запуске бота"""
        if self.monitor_service:
            self.monitor_service.start()
    
    async def on_shutdown(self, *args, **kwargs):
        """Действия при остановке бота"""
        if self.monitor_service:
            self.monitor_service.stop()
    
    async def start_polling(self):
        """Запускает polling бота"""
        self.dispatcher.startup.register(self.on_startup)
        self.dispatcher.shutdown.register(self.on_shutdown)
        await self.dispatcher.start_polling(self.bot, skip_updates=True)
