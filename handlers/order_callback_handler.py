from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from services.retailcrm_service import RetailCRMService
from database.db_service import DatabaseService
from config.settings import Settings
from services.rate_limiter import get_rate_limiter  # ← ДОБАВЛЕНО
import logging
import re
from typing import Optional, Tuple


router = Router()
logger = logging.getLogger(__name__)


# ============ ИНИЦИАЛИЗАЦИЯ REDIS RATE LIMITER ============
rate_limiter = get_rate_limiter(
    host=Settings.get_redis_host(),
    port=Settings.get_redis_port(),
    db=Settings.get_redis_db()
)


# ============ HELPER ДЛЯ RATE LIMITING ============
async def check_rate_limit_for_user(
    callback: CallbackQuery,
    action: str,
    limit: int = 10,
    window: int = 60
) -> bool:
    """
    Проверяет rate limit для пользователя
    
    Args:
        callback: CallbackQuery
        action: Название действия
        limit: Максимум запросов (по умолчанию 10)
        window: Окно времени в секундах (по умолчанию 60)
    
    Returns:
        True если лимит превышен (нужно блокировать)
    """
    user_id = callback.from_user.id
    
    is_limited, remaining = await rate_limiter.check_rate_limit(
        identifier=str(user_id),
        action=action,
        limit=limit,
        window=window
    )
    
    if is_limited:
        # Получаем время до сброса
        remaining_time = rate_limiter.get_remaining_time(str(user_id), action)
        
        await callback.answer(
            f"⚠️ Слишком много действий!\n"
            f"Подождите {remaining_time} секунд.",
            show_alert=True
        )
        
        logger.warning(
            f"⚠️ Rate limit для user {user_id} ({callback.from_user.username}): "
            f"action={action}, осталось {remaining_time}s"
        )
        return True
    
    return False


# ============ ПАРСИНГ CALLBACK DATA ============


def parse_callback_data(callback_data: str, action: str) -> Optional[int]:
    """
    Безопасно парсит callback_data и извлекает order_id
    
    Args:
        callback_data: Строка вида "confirm_order:12345"
        action: Действие (confirm_order, bouquet_ready и т.д.)
    
    Returns:
        order_id (int) или None если парсинг не удался
    
    Примеры:
        parse_callback_data("confirm_order:12345", "confirm_order") → 12345
        parse_callback_data("confirm_order", "confirm_order") → None (без ID)
        parse_callback_data("confirm_order:abc", "confirm_order") → None (не число)
        parse_callback_data("confirm_order::", "confirm_order") → None (пустое)
    """
    
    try:
        # Проверяем что callback_data не None/пусто
        if not callback_data or not isinstance(callback_data, str):
            logger.warning(f"❌ Некорректный callback_data: {callback_data} (type: {type(callback_data)})")
            return None
        
        # Проверяем что starts with действия
        if not callback_data.startswith(f"{action}:"):
            logger.warning(f"❌ callback_data не соответствует действию '{action}': {callback_data}")
            return None
        
        # Извлекаем часть после ':'
        parts = callback_data.split(":")
        
        # Проверяем что ровно 2 части (action:id)
        if len(parts) != 2:
            logger.warning(
                f"❌ Неверный формат callback_data '{callback_data}': "
                f"ожидается '{action}:ID', получено {len(parts)} частей"
            )
            return None
        
        # Извлекаем и проверяем ID
        id_str = parts[1].strip()
        
        # Проверяем что ID не пусто
        if not id_str:
            logger.warning(f"❌ ID отсутствует в callback_data: {callback_data}")
            return None
        
        # Пробуем конвертировать в int
        order_id = int(id_str)
        
        # Проверяем что ID положительный
        if order_id <= 0:
            logger.warning(f"❌ ID должен быть > 0: {order_id}")
            return None
        
        return order_id
    
    except ValueError as e:
        logger.warning(f"❌ ID не является числом в callback_data '{callback_data}': {e}")
        return None
    
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при парсинге callback_data '{callback_data}': {e}", exc_info=True)
        return None



# ============ HELPER ФУНКЦИИ ============


async def safe_send_message(callback: CallbackQuery, text: str, **kwargs):
    """Безопасная отправка сообщения с проверкой наличия callback.message"""
    if callback.message:
        await callback.message.answer(text, **kwargs)
    else:
        await callback.answer(text, show_alert=True)



async def safe_edit_markup(callback: CallbackQuery, markup):
    """Безопасное редактирование клавиатуры"""
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=markup)
    else:
        logger.warning(f"Невозможно отредактировать клавиатуру: callback.message отсутствует")



# ============ ОБРАБОТЧИКИ ============


@router.callback_query(F.data.startswith("confirm_order:"))
async def handle_confirm_order(callback: CallbackQuery):
    """Обработчик подтверждения заказа"""
    
    # ⭐ ПРОВЕРКА RATE LIMIT (5 подтверждений в минуту)
    if await check_rate_limit_for_user(
        callback,
        action='confirm_order',
        limit=5,
        window=60
    ):
        return  # Лимит превышен, прерываем
    
    # 🔒 Безопасный парсинг callback_data
    order_id = parse_callback_data(callback.data, "confirm_order")
    if order_id is None:
        await callback.answer("❌ Ошибка: неверный формат данных", show_alert=True)
        return
    
    try:
        user_id = callback.from_user.id
        username = callback.from_user.username or callback.from_user.first_name or "Неизвестно"
        logger.info(f"Пользователь {username} (ID: {user_id}) подтверждает заказ {order_id}")
        
        await callback.answer("⏳ Обновляю статус заказа...")
        
        retailcrm_service = RetailCRMService(
            api_key=Settings.get_retailcrm_api_key(),
            domain=Settings.get_retailcrm_domain()
        )
        
        order = retailcrm_service.get_order_by_id(order_id)
        if not order:
            await safe_send_message(callback, "❌ Заказ не найден в системе")
            return
        
        old_status = order.get('status')
        order_number = order.get('number', order_id)
        
        # Получаем тип доставки
        db = DatabaseService()
        delivery_type = db.get_order_delivery_type(order_id)
        
        # ✅ НОВАЯ ЛОГИКА: для самовывоза свой статус
        if delivery_type == 'self-delivery':
            # Для самовывоза: сразу "Передан на самовывоз"
            new_status = Settings.get_status_self_pickup_ready()
            action_text = 'Статус: Передан на самовывоз'
        else:
            # Для доставки: "Передан в комплектацию"
            new_status = Settings.get_status_confirmed()
            action_text = 'Статус: Передан в комплектацию'
        
        # Обновляем статус
        success = retailcrm_service.update_order_status(
            order_id,
            new_status
        )
        
        if success:
            db.log_order_action(
                order_id=order_id,
                admin_id=user_id,
                action='confirmed',
                comment=f'Статус изменен: {old_status} → {new_status}'
            )
            
            # Выбираем следующую кнопку в зависимости от типа доставки
            if delivery_type == 'self-delivery':
                # Для самовывоза - кнопка "Заказ забрали"
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(
                            text="🛍️ Заказ забрали",
                            callback_data=f"picked_up:{order_id}"
                        )]
                    ]
                )
                await safe_edit_markup(callback, keyboard)

                await callback.answer(
                    "✅ Заказ подтвержден! Статус: 'Передан в комплектацию'",
                    show_alert=True
                )

                # Инструкция про фото букета
                await safe_send_message(
                    callback,
                    f"✅ <b>ЗАКАЗ #{order_number} ПОДТВЕРЖДЕН</b>\n\n"
                    f"📸 Отправьте фото готового букета",
                    parse_mode="HTML"
                )
            else:
                # ✅ ДЛЯ ДОСТАВКИ: Убираем кнопки полностью
                await safe_edit_markup(callback, None)

                await callback.answer(
                    "✅ Заказ подтвержден! Статус: 'Передан в комплектацию'",
                    show_alert=True
                )

                # Инструкция про фото букета
                await safe_send_message(
                    callback,
                    f"✅ <b>ЗАКАЗ #{order_number} ПОДТВЕРЖДЕН</b>\n\n"
                    f"📸 Отправьте фото готового букета\n\n"
                    f"⏳ После этого измените статус в RetailCRM на '<b>Букет готов</b>'",
                    parse_mode="HTML"
                )
            
            logger.info(f"✅ Заказ {order_id} подтвержден (тип: {delivery_type})")
        else:
            await safe_send_message(callback, "❌ Не удалось обновить статус заказа")
            logger.error(f"Не удалось обновить статус заказа {order_id}")
    
    except Exception as e:
        logger.error(f"Ошибка при подтверждении заказа {order_id}: {e}", exc_info=True)
        await safe_send_message(callback, "❌ Произошла ошибка при обработке заказа")

@router.callback_query(F.data.startswith("order_picked_up_by_courier:"))
async def handle_order_picked_up_by_courier(callback: CallbackQuery):
    """Обработчик кнопки 'Передан курьеру' (только для доставки)"""

    # ⭐ ПРОВЕРКА RATE LIMIT
    if await check_rate_limit_for_user(callback, action='order_picked_up_by_courier', limit=10, window=60):
        return

    # 🔒 Безопасный парсинг callback_data
    order_id = parse_callback_data(callback.data, "order_picked_up_by_courier")
    if order_id is None:
        await callback.answer("❌ Ошибка: неверный формат данных", show_alert=True)
        return

    try:
        user_id = callback.from_user.id
        username = callback.from_user.username or callback.from_user.first_name or "Неизвестно"

        logger.info(f"Заказ {order_id} передан курьеру, пользователь {username}")

        await callback.answer("✅ Принято!")

        retailcrm_service = RetailCRMService(
            api_key=Settings.get_retailcrm_api_key(),
            domain=Settings.get_retailcrm_domain()
        )

        order = retailcrm_service.get_order_by_id(order_id)
        if not order:
            await safe_send_message(callback, "❌ Заказ не найден в системе")
            return

        order_number = order.get('number', order_id)

        # ✅ НЕ меняем статус! Только логируем и убираем кнопку
        db = DatabaseService()
        db.log_order_action(
            order_id=order_id,
            admin_id=user_id,
            action='picked_up_by_courier',
            comment=f'Заказ передан курьеру (статус не изменён)'
        )

        # Убираем кнопку
        await safe_edit_markup(callback, None)

        # Просьба о чеке
        await safe_send_message(
            callback,
            f"✅ <b>ЗАКАЗ #{order_number} ПЕРЕДАН КУРЬЕРУ</b>\n\n"
            f"🧾 Отправьте фото чека",
            parse_mode="HTML"
        )

        logger.info(f"✅ Заказ {order_id} передан курьеру (без изменения статуса)")

    except Exception as e:
        logger.error(f"Ошибка при обработке 'Передан курьеру' для заказа {order_id}: {e}", exc_info=True)
        await safe_send_message(callback, "❌ Произошла ошибка")


# @router.callback_query(F.data.startswith("bouquet_ready:"))
# async def handle_bouquet_ready(callback: CallbackQuery):
#     """Обработчик кнопки 'Букет готов' (только для доставки)"""
    
#     # ⭐ ПРОВЕРКА RATE LIMIT (10 раз в минуту)
#     if await check_rate_limit_for_user(
#         callback,
#         action='bouquet_ready',
#         limit=10,
#         window=60
#     ):
#         return
    
#     # 🔒 Безопасный парсинг callback_data
#     order_id = parse_callback_data(callback.data, "bouquet_ready")
#     if order_id is None:
#         await callback.answer("❌ Ошибка: неверный формат данных", show_alert=True)
#         return
    
#     try:
#         await callback.answer("⏳ Обновляю статус...")
        
#         user_id = callback.from_user.id
#         username = callback.from_user.username or callback.from_user.first_name or "Неизвестно"
#         logger.info(f"Букет готов для заказа {order_id}, пользователь {username}")
        
#         retailcrm_service = RetailCRMService(
#             api_key=Settings.get_retailcrm_api_key(),
#             domain=Settings.get_retailcrm_domain()
#         )
        
#         order = retailcrm_service.get_order_by_id(order_id)
#         if not order:
#             await safe_send_message(callback, "❌ Заказ не найден в системе")
#             return
        
#         old_status = order.get('status')
#         order_number = order.get('number', order_id)
        
#         # Обновляем статус на "Букет готов"
#         success = retailcrm_service.update_order_status(
#             order_id, 
#             Settings.get_status_bouquet_ready()
#         )
        
#         if success:
#             db = DatabaseService()
#             db.log_order_action(
#                 order_id=order_id,
#                 admin_id=user_id,
#                 action='bouquet_ready',
#                 comment=f'Букет готов. Статус: {old_status} → {Settings.get_status_bouquet_ready()}'
#             )
            
#             # Следующая кнопка - "Передан в доставку"
#             keyboard = InlineKeyboardMarkup(
#                 inline_keyboard=[
#                     [InlineKeyboardButton(
#                         text="🚚 Передан в доставку",
#                         callback_data=f"sent_to_delivery:{order_id}"
#                     )]
#                 ]
#             )
            
#             await safe_edit_markup(callback, keyboard)
#             await callback.answer("✅ Букет готов! Статус обновлён", show_alert=True)
            
#             logger.info(f"✅ Букет готов для заказа {order_id}")
#         else:
#             await safe_send_message(callback, "❌ Не удалось обновить статус")
#             logger.error(f"Не удалось обновить статус заказа {order_id}")
    
#     except Exception as e:
#         logger.error(f"Ошибка при обработке 'Букет готов' для заказа {order_id}: {e}", exc_info=True)
#         await safe_send_message(callback, "❌ Произошла ошибка")



# @router.callback_query(F.data.startswith("sent_to_delivery:"))
# async def handle_sent_to_delivery(callback: CallbackQuery):
#     """Обработчик кнопки 'Передан в доставку' (только для доставки)"""
    
#     # ⭐ ПРОВЕРКА RATE LIMIT (10 раз в минуту)
#     if await check_rate_limit_for_user(
#         callback,
#         action='sent_to_delivery',
#         limit=10,
#         window=60
#     ):
#         return
    
#     # 🔒 Безопасный парсинг callback_data
#     order_id = parse_callback_data(callback.data, "sent_to_delivery")
#     if order_id is None:
#         await callback.answer("❌ Ошибка: неверный формат данных", show_alert=True)
#         return
    
#     try:
#         user_id = callback.from_user.id
#         username = callback.from_user.username or callback.from_user.first_name or "Неизвестно"
#         logger.info(f"Передан в доставку заказ {order_id}, пользователь {username}")
        
#         await callback.answer("⏳ Обновляю статус...")
        
#         retailcrm_service = RetailCRMService(
#             api_key=Settings.get_retailcrm_api_key(),
#             domain=Settings.get_retailcrm_domain()
#         )
        
#         order = retailcrm_service.get_order_by_id(order_id)
#         if not order:
#             await safe_send_message(callback, "❌ Заказ не найден в системе")
#             return
        
#         old_status = order.get('status')
#         order_number = order.get('number', order_id)
        
#         # Обновляем статус на "Передан в доставку"
#         success = retailcrm_service.update_order_status(
#             order_id, 
#             Settings.get_status_sent_to_delivery()
#         )
        
#         if success:
#             db = DatabaseService()
#             db.log_order_action(
#                 order_id=order_id,
#                 admin_id=user_id,
#                 action='sent_to_delivery',
#                 comment=f'Передан в доставку. Статус: {old_status} → {Settings.get_status_sent_to_delivery()}'
#             )
            
#             # Следующая кнопка - "Выполнен"
#             keyboard = InlineKeyboardMarkup(
#                 inline_keyboard=[
#                     [InlineKeyboardButton(
#                         text="✅ Выполнен",
#                         callback_data=f"completed:{order_id}"
#                     )]
#                 ]
#             )
            
#             await safe_edit_markup(callback, keyboard)
#             await callback.answer("✅ Передан в доставку!", show_alert=True)
            
#             # Просьба о фото чека
#             await safe_send_message(
#                 callback,
#                 # f"📋 Следующий шаг:\n"
#                 f"Отправьте: <b>Фото</b> чека 🧾\n",
#                 parse_mode="HTML"
#             )
            
#             logger.info(f"✅ Заказ {order_id} передан в доставку")
#         else:
#             await safe_send_message(callback, "❌ Не удалось обновить статус")
#             logger.error(f"Не удалось обновить статус заказа {order_id}")
    
#     except Exception as e:
#         logger.error(f"Ошибка при обработке 'Передан в доставку' для заказа {order_id}: {e}", exc_info=True)
#         await safe_send_message(callback, "❌ Произошла ошибка")



# @router.callback_query(F.data.startswith("completed:"))
# async def handle_completed(callback: CallbackQuery):
#     """Обработчик кнопки 'Выполнен' (для доставки)"""
    
#     # ⭐ ПРОВЕРКА RATE LIMIT (10 раз в минуту)
#     if await check_rate_limit_for_user(
#         callback,
#         action='completed',
#         limit=10,
#         window=60
#     ):
#         return
    
#     # 🔒 Безопасный парсинг callback_data
#     order_id = parse_callback_data(callback.data, "completed")
#     if order_id is None:
#         await callback.answer("❌ Ошибка: неверный формат данных", show_alert=True)
#         return
    
#     try:
#         user_id = callback.from_user.id
#         username = callback.from_user.username or callback.from_user.first_name or "Неизвестно"
#         logger.info(f"Заказ {order_id} выполнен, пользователь {username}")
        
#         await callback.answer("⏳ Завершаю заказ...")
        
#         retailcrm_service = RetailCRMService(
#             api_key=Settings.get_retailcrm_api_key(),
#             domain=Settings.get_retailcrm_domain()
#         )
        
#         order = retailcrm_service.get_order_by_id(order_id)
#         if not order:
#             await safe_send_message(callback, "❌ Заказ не найден в системе")
#             return
        
#         old_status = order.get('status')
#         order_number = order.get('number', order_id)
        
#         # Обновляем статус на "Выполнен"
#         success = retailcrm_service.update_order_status(
#             order_id, 
#             Settings.get_status_completed()
#         )
        
#         if success:
#             db = DatabaseService()
#             db.log_order_action(
#                 order_id=order_id,
#                 admin_id=user_id,
#                 action='completed',
#                 comment=f'Заказ выполнен. Статус: {old_status} → {Settings.get_status_completed()}'
#             )
            
#             # Убираем кнопки
#             await safe_edit_markup(callback, None)
#             await callback.answer("✅ Заказ выполнен!", show_alert=True)
            
#             # Финальное сообщение
#             await safe_send_message(
#                 callback,
#                 f"✅ Заказ #{order_number} успешно выполнен",
#                 parse_mode="HTML"
#             )
            
#             logger.info(f"✅ Заказ {order_id} успешно выполнен")
#         else:
#             await safe_send_message(callback, "❌ Не удалось завершить заказ")
#             logger.error(f"Не удалось завершить заказ {order_id}")
    
#     except Exception as e:
#         logger.error(f"Ошибка при завершении заказа {order_id}: {e}", exc_info=True)
#         await safe_send_message(callback, "❌ Произошла ошибка")



@router.callback_query(F.data.startswith("picked_up:"))
async def handle_picked_up(callback: CallbackQuery):
    """Обработчик 'Букет готов' (только для самовывоза)"""
    
    # ⭐ ПРОВЕРКА RATE LIMIT
    if await check_rate_limit_for_user(callback, action='picked_up', limit=10, window=60):
        return
    
    # 🔒 Безопасный парсинг callback_data
    order_id = parse_callback_data(callback.data, "picked_up")
    if order_id is None:
        await callback.answer("❌ Ошибка: неверный формат данных", show_alert=True)
        return
    
    try:
        user_id = callback.from_user.id
        username = callback.from_user.username or callback.from_user.first_name or "Неизвестно"
        
        logger.info(f"Букет готов для заказа {order_id}, пользователь {username}")
        
        await callback.answer("⏳ Обновляю статус...")
        
        retailcrm_service = RetailCRMService(
            api_key=Settings.get_retailcrm_api_key(),
            domain=Settings.get_retailcrm_domain()
        )
        
        order = retailcrm_service.get_order_by_id(order_id)
        if not order:
            await safe_send_message(callback, "❌ Заказ не найден в системе")
            return
        
        old_status = order.get('status')
        order_number = order.get('number', order_id)
        
        # ✅ НОВОЕ: Для самовывоза ставим сразу "Выполнен"
        success = retailcrm_service.update_order_status(
            order_id,
            Settings.get_status_completed()  # ✅ complete вместо buket-gotov
        )
        
        if success:
            db = DatabaseService()
            db.log_order_action(
                order_id=order_id,
                admin_id=user_id,
                action='completed',  # ✅ completed вместо bouquet_ready
                comment=f'Заказ выполнен (самовывоз). Статус: {old_status} → {Settings.get_status_completed()}'
            )
            
            await safe_edit_markup(callback, None)
            await callback.answer("✅ Заказ выполнен!", show_alert=True)  # ✅ Изменён текст
            
            await safe_send_message(
                callback,
                f"✅ <b>ЗАКАЗ #{order_number} ВЫПОЛНЕН</b>\n\n"  # ✅ Изменён текст
                f"🧾 Отправьте фото чека",
                parse_mode="HTML"
            )
            
            logger.info(f"✅ Заказ {order_id} выполнен (самовывоз)")
        else:
            await safe_send_message(callback, "❌ Не удалось обновить статус")
    
    except Exception as e:
        logger.error(f"Ошибка при обработке 'Букет готов' для заказа {order_id}: {e}", exc_info=True)
        await safe_send_message(callback, "❌ Произошла ошибка")



# @router.callback_query(F.data.startswith("reject_order:"))
# async def handle_reject_order(callback: CallbackQuery):
#     """Обработчик отклонения заказа"""
    
#     # ⭐ ПРОВЕРКА RATE LIMIT (3 раза в минуту - строже!)
#     if await check_rate_limit_for_user(
#         callback,
#         action='reject_order',
#         limit=3,
#         window=60
#     ):
#         return
    
#     # 🔒 Безопасный парсинг callback_data
#     order_id = parse_callback_data(callback.data, "reject_order")
#     if order_id is None:
#         await callback.answer("❌ Ошибка: неверный формат данных", show_alert=True)
#         return
    
#     try:
#         user_id = callback.from_user.id
#         username = callback.from_user.username or callback.from_user.first_name or "Неизвестно"
#         logger.info(f"Пользователь {username} (ID: {user_id}) отклоняет заказ {order_id}")
        
#         await callback.answer("⏳ Отклоняю заказ...")
        
#         retailcrm_service = RetailCRMService(
#             api_key=Settings.get_retailcrm_api_key(),
#             domain=Settings.get_retailcrm_domain()
#         )
        
#         order = retailcrm_service.get_order_by_id(order_id)
#         if not order:
#             await safe_send_message(callback, "❌ Заказ не найден в системе")
#             return
        
#         old_status = order.get('status')
#         order_number = order.get('number', order_id)
        
#         # Обновляем статус на "Отменен"
#         success = retailcrm_service.update_order_status(
#             order_id, 
#             Settings.get_status_rejected()
#         )
        
#         if success:
#             db = DatabaseService()
#             db.log_order_action(
#                 order_id=order_id,
#                 admin_id=user_id,
#                 action='rejected',
#                 comment=f'Статус изменен: {old_status} → {Settings.get_status_rejected()}'
#             )
            
#             # Убираем клавиатуру
#             await safe_edit_markup(callback, None)
#             await callback.answer("❌ Заказ отклонен", show_alert=True)
            
#             await safe_send_message(
#                 callback,
#                 f"❌ Заказ #{order_number} отклонен\n\n"
#                 f"Статус изменен на 'Отменен'",
#                 parse_mode="HTML"
#             )
            
#             logger.info(f"❌ Заказ {order_id} отклонен")
#         else:
#             await safe_send_message(callback, "❌ Не удалось отклонить заказ")
#             logger.error(f"Не удалось отклонить заказ {order_id}")
    
#     except Exception as e:
#         logger.error(f"Ошибка при отклонении заказа {order_id}: {e}", exc_info=True)
#         await safe_send_message(callback, "❌ Произошла ошибка при отклонении заказа")



@router.callback_query(F.data.startswith("discuss_replacement:"))
async def handle_discuss_replacement(callback: CallbackQuery):
    """Обработчик кнопки 'Обсудить замены' - переводит в статус 'no-product'"""
    
    # ⭐ ПРОВЕРКА RATE LIMIT (5 раз в минуту)
    if await check_rate_limit_for_user(
        callback,
        action='discuss_replacement',
        limit=5,
        window=60
    ):
        return
    
    # 🔒 Безопасный парсинг callback_data
    order_id = parse_callback_data(callback.data, "discuss_replacement")
    if order_id is None:
        await callback.answer("❌ Ошибка: неверный формат данных", show_alert=True)
        return
    
    try:
        user_id = callback.from_user.id
        username = callback.from_user.username or callback.from_user.first_name or "Неизвестно"
        logger.info(f"Пользователь {username} (ID: {user_id}) нажал 'Обсудить замены' для заказа {order_id}")
        
        await callback.answer("⏳ Переводим в статус 'Обсуждение замен'...")
        
        retailcrm_service = RetailCRMService(
            api_key=Settings.get_retailcrm_api_key(),
            domain=Settings.get_retailcrm_domain()
        )
        
        order = retailcrm_service.get_order_by_id(order_id)
        if not order:
            await safe_send_message(callback, "❌ Заказ не найден в системе")
            return
        
        old_status = order.get('status')
        order_number = order.get('number', order_id)
        
        # Обновляем статус на "Товара нет"
        success = retailcrm_service.update_order_status(
            order_id, 
            Settings.get_status_discussion()
        )
        
        if success:
            db = DatabaseService()
            
            # Отмечаем что этот заказ был в obsuzhdenie-zameny
            db.mark_order_in_no_product(order_id)
            
            # Логируем действие
            db.log_order_action(
                order_id=order_id,
                admin_id=user_id,
                action='discuss_replacement',
                comment=f'Нет товара в наличии. Статус: {old_status} → {Settings.get_status_discussion()}'
            )
            
            await safe_edit_markup(callback, None)
            await callback.answer("✅ Статус изменён на 'Обсуждение замен'", show_alert=True)
            
            await safe_send_message(
                callback,
                f"🔄 Заказ #{order_number} требует обсуждения замен\n\n"
                f"📋 Статус изменён: Обсуждение замен",
                parse_mode="HTML"
            )
            
            logger.info(f"✅ Заказ {order_id} переведён в статус 'obsuzhdenie-zameny' (обсуждение замен)")
        else:
            await safe_send_message(callback, "❌ Не удалось обновить статус заказа")
            logger.error(f"Не удалось обновить статус заказа {order_id} на 'obsuzhdenie-zameny'")
    
    except Exception as e:
        logger.error(f"Ошибка при обработке 'Обсудить замены' для заказа {order_id}: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)
