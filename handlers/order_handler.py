from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from states.order_states import OrderStates
from services.retailcrm_service import RetailCRMService
from services.order_formatter_service import OrderFormatterService
from config.settings import Settings

router = Router()


@router.callback_query(F.data == "find_order")
async def handle_find_order_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик нажатия на кнопку поиска заказа"""
    await callback.message.answer("Введите номер заказа:")
    await state.set_state(OrderStates.waiting_for_order_number)
    await callback.answer()


@router.message(OrderStates.waiting_for_order_number)
async def handle_order_number_input(message: Message, state: FSMContext):
    """Обработчик ввода номера заказа"""
    order_number = message.text.strip()
    
    await message.answer("🔍 Ищу информацию о заказе...")
    
    try:
        retailcrm_service = RetailCRMService(
            api_key=Settings.get_retailcrm_api_key(),
            domain=Settings.get_retailcrm_domain()
        )
        
        order = retailcrm_service.get_order_by_number(order_number)
        
        if order:
            formatted_info = OrderFormatterService.format_order_info(order)
            await message.answer(formatted_info)
        else:
            await message.answer(
                f"❌ Заказ №{order_number} не найден\n\n"
                f"Проверьте:\n"
                f"• Правильность номера заказа\n"
                f"• Доступ API ключа к этому заказу\n"
                f"• Настройки домена в .env"
            )
    
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка: {str(e)}")
    
    await state.clear()


@router.message(Command("check_status"))
async def handle_check_status_command(message: Message):
    """Команда для ручной проверки заказов с целевым статусом"""
    await message.answer("🔍 Проверяю заказы...")
    
    try:
        retailcrm_service = RetailCRMService(
            api_key=Settings.get_retailcrm_api_key(),
            domain=Settings.get_retailcrm_domain()
        )
        
        status_code = "otpravit-v-magazin-ne-trogat"
        orders = retailcrm_service.get_orders_by_status(status_code)
        
        if orders and len(orders) > 0:
            message_text = (
                f"✅ Найдено заказов со статусом "
                f"'Отправить в магазин(не трогать)': {len(orders)}\n\n"
            )
            
            for order in orders[:10]:
                order_number = order.get('number', 'N/A')
                total_sum = order.get('totalSumm', 0)
                message_text += f"📦 Заказ №{order_number} - {total_sum} руб.\n"
            
            await message.answer(message_text)
        else:
            await message.answer("❌ Заказов с данным статусом не найдено")
    
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
