from typing import Callable, Dict, Any, Awaitable, List
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from config.settings import Settings
import logging

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    """Middleware для проверки прав доступа к боту"""
    
    def __init__(self, allowed_chat_ids: List[str]):
        super().__init__()
        self.allowed_chat_ids = set(allowed_chat_ids)
        logger.info(f"AuthMiddleware инициализирован для {len(self.allowed_chat_ids)} пользователей")
    
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        """Проверяет доступ пользователя к боту"""
        
        # Получаем ID пользователя
        if isinstance(event, Message):
            user_id = str(event.from_user.id)
            chat_id = str(event.chat.id)
        elif isinstance(event, CallbackQuery):
            user_id = str(event.from_user.id)
            chat_id = str(event.message.chat.id)
        else:
            return await handler(event, data)
        
        # Проверяем, есть ли пользователь в списке разрешённых
        if chat_id not in self.allowed_chat_ids and user_id not in self.allowed_chat_ids:
            logger.warning(f"Отказано в доступе для пользователя {user_id} (chat: {chat_id})")
            
            # Отправляем сообщение о недоступности
            if isinstance(event, Message):
                await event.answer(
                    "⛔️ У вас нет доступа к этому боту.\n"
                    "Обратитесь к администратору для получения доступа."
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "⛔️ У вас нет доступа к этому боту",
                    show_alert=True
                )
            
            return  # Прерываем обработку
        
        # Если доступ разрешён - продолжаем обработку
        return await handler(event, data)
