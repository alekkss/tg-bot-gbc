from aiogram import Router, F
from aiogram.types import CallbackQuery
from services.retailcrm_service import RetailCRMService
from services.status_formatter_service import StatusFormatterService
from config.settings import Settings

router = Router()


@router.callback_query(F.data == "show_statuses")
async def handle_show_statuses_callback(callback: CallbackQuery):
    """Обработчик нажатия на кнопку просмотра статусов"""
    await callback.message.answer("🔍 Загружаю список статусов...")
    
    try:
        retailcrm_service = RetailCRMService(
            api_key=Settings.get_retailcrm_api_key(),
            domain=Settings.get_retailcrm_domain()
        )
        
        statuses = retailcrm_service.get_all_statuses()
        
        if statuses:
            formatted_info = StatusFormatterService.format_statuses_list(statuses)
            
            # Telegram имеет ограничение на длину сообщения (4096 символов)
            # Разбиваем длинное сообщение на части если нужно
            max_length = 4000
            if len(formatted_info) <= max_length:
                await callback.message.answer(formatted_info)
            else:
                # Разбиваем на части
                parts = []
                current_part = []
                current_length = 0
                
                for line in formatted_info.split('\n'):
                    line_length = len(line) + 1
                    if current_length + line_length > max_length:
                        parts.append('\n'.join(current_part))
                        current_part = [line]
                        current_length = line_length
                    else:
                        current_part.append(line)
                        current_length += line_length
                
                if current_part:
                    parts.append('\n'.join(current_part))
                
                for part in parts:
                    await callback.message.answer(part)
        else:
            await callback.message.answer("❌ Не удалось загрузить список статусов")
    
    except Exception as e:
        await callback.message.answer(f"❌ Произошла ошибка: {str(e)}")
    
    await callback.answer()
