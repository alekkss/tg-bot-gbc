from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
import logging

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("getchatid"))
async def get_chat_id(message: Message):
    """Показывает ID текущего чата"""
    chat_id = message.chat.id
    chat_type = message.chat.type
    chat_title = message.chat.title or message.chat.first_name or "Личный чат"
    
    await message.answer(
        f"📊 <b>Информация о чате:</b>\n\n"
        f"🆔 ID: <code>{chat_id}</code>\n"
        f"📝 Название: {chat_title}\n"
        f"🔖 Тип: {chat_type}\n\n"
        f"<i>Скопируйте ID для использования в .env</i>",
        parse_mode="HTML"
    )
    
    logger.info(f"Запрошен ID чата: {chat_id} ({chat_title})")
