from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from keyboards.inline_keyboards import OrderKeyboards

router = Router()


@router.message(Command("start"))
async def handle_start_command(message: Message):
    """Обработчик команды /start"""
    await message.answer(
        "Здравствуйте! Выберите действие:",
        reply_markup=OrderKeyboards.get_main_menu()
    )
