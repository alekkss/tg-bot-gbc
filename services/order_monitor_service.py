import asyncio
import time
from datetime import datetime, time as dt_time, timedelta
from typing import Dict, List, Tuple
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from services.retailcrm_service import RetailCRMService
from database.db_service import DatabaseService
from config.settings import Settings
import logging
import re

logger = logging.getLogger(__name__)


class OrderMonitorService:
    """Сервис для мониторинга заказов в фоновом режиме"""
    
    # TARGET_STATUS_CODE = "otpravit-v-magazin-ne-trogat"
    CHECK_INTERVAL = 60  # 1 минута
    CACHE_REFRESH_TIME = dt_time(0, 0)  # 00:00
    
    def __init__(self, bot: Bot, retailcrm_service: RetailCRMService, admin_config: Dict[str, Dict[str, str]]):
        """
        Args:
            bot: Экземпляр бота
            retailcrm_service: Сервис RetailCRM
            admin_config: Полная конфигурация {user_id: {"warehouse": "20", "chat_id": "-123"}}
        """
        self.bot = bot
        self.retailcrm_service = retailcrm_service
        self.admin_config = admin_config
        self.is_running = False
        self.task = None
        self.last_cache_refresh_date = None

        # ✅ Загружаем статусы из Settings
        self.TARGET_STATUS_CODE = Settings.get_status_target()
        self.STATUS_RETURNED = Settings.get_status_returned_from_discussion()
        
        # Инициализируем БД
        self.db = DatabaseService()
        logger.info("DatabaseService инициализирован в OrderMonitorService")
        
        logger.info(f"Настроена фильтрация по складам для {len(admin_config)} администраторов:")
        for user_id, config in admin_config.items():
            warehouse = config['warehouse']
            chat_id = config['chat_id']
            logger.info(f"  • Admin {user_id} → Склад {warehouse} → Чат {chat_id}")
    
    def get_admins_for_warehouse(self, warehouse_code: str) -> List[Tuple[str, str]]:
        """
        Получает список (user_id, chat_id) для указанного склада
        
        Returns:
            [(user_id, chat_id), (user_id, chat_id), ...]
        """
        admins = [
            (user_id, config['chat_id'])
            for user_id, config in self.admin_config.items()
            if config['warehouse'] == warehouse_code
        ]
        return admins
    
    def create_order_keyboard(self, order_id: int) -> InlineKeyboardMarkup:
        """Создаёт клавиатуру для уведомления о новом заказе"""
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Заказ принят",
                        callback_data=f"confirm_order:{order_id}"
                    ),
                    InlineKeyboardButton(
                        text="🔄 Обсудить замены",
                        callback_data=f"discuss_replacement:{order_id}"
                    )
                ]
            ]
        )
        return keyboard
    
    def format_order_notification(self, order: Dict) -> str:
        """Форматирует сообщение с информацией о заказе"""
        lines = []
        
        # Номер заказа
        order_number = order.get('number', 'N/A')
        lines.append(f"<b>ЗАКАЗ {order_number}</b>")
        lines.append("")
        
        # Товары
        if 'items' in order and order['items']:
            lines.append("<b>ТОВАРЫ:</b>")
            lines.append("")
            item_counter = 1  # Счётчик для нумерации
            
            for item in order['items']:
                offer = item.get('offer', {})
                item_name = offer.get('displayName', offer.get('name', 'N/A'))
                quantity = item.get('quantity', 0)
                properties = offer.get('properties', {})
                
                # Дублируем товар quantity раз
                for _ in range(quantity):
                    lines.append(f"<b>{item_counter}. {item_name}</b>")
                    lines.append("")
                    
                    # Состав (если есть)
                    if properties.get('sostav'):
                        lines.append("Состав:")
                        lines.append(f"   {properties['sostav']}")
                        lines.append("")
                    
                    item_counter += 1
            
            if lines and lines[-1] == "":
                lines.pop()  # Убираем последнюю пустую строку
            
            lines.append("")
        
        # Проверяем тип доставки
        delivery = order.get('delivery', {})
        delivery_type_code = delivery.get('code', '')
        
        # Определяем тип доставки
        if delivery_type_code == 'self-delivery':
            delivery_type_text = "🏪 САМОВЫВОЗ"
        else:
            delivery_type_text = "🚚 ДОСТАВКА"
        
        lines.append(f"<b>{delivery_type_text}</b>")
        lines.append("")
        
        # Склад отгрузки
        stores_data = self.retailcrm_service.get_stores()
        shipment_store_code = order.get('shipmentStore')
        
        if shipment_store_code and stores_data:
            if isinstance(stores_data, dict):
                store_info = stores_data.get(shipment_store_code, {})
            elif isinstance(stores_data, list):
                store_info = next((s for s in stores_data if s.get('code') == shipment_store_code), {})
            else:
                store_info = {}
            
            if store_info:
                store_name = store_info.get('name', 'N/A')
                lines.append(f"<b>Склад отгрузки:</b> {store_name}")
                lines.append("")
        
        
        
        # Дата и время доставки
        if 'delivery' in order:
            delivery = order['delivery']
            
            # Дата доставки
            delivery_date = delivery.get('date', 'N/A')
            lines.append(f"📅 <b>Дата заказа:</b> {delivery_date}")
            
            # Время доставки
            if 'time' in delivery:
                time_info = delivery['time']
                time_str = None
                
                if isinstance(time_info, dict):
                    # Сначала пробуем custom
                    time_str = time_info.get('custom')
                    
                    # Если нет custom, используем from и to
                    if not time_str:
                        time_from = time_info.get('from', '')
                        time_to = time_info.get('to', '')
                        
                        # Корректируем время (-1 час)
                        time_from_adjusted = self._adjust_time(time_from, hours=-1)
                        time_to_adjusted = self._adjust_time(time_to, hours=-1)
                        
                        if time_from_adjusted and time_to_adjusted:
                            time_str = f"{time_from_adjusted} - {time_to_adjusted}"
                        elif time_from_adjusted:
                            time_str = f"с {time_from_adjusted}"
                    else:
                        # Корректируем custom время
                        time_str = self._adjust_custom_time(time_str, hours=-1)
                
                elif isinstance(time_info, str):
                    time_str = self._adjust_custom_time(time_info, hours=-1)
                
                if time_str:
                    lines.append(f"⏰ <b>Время заказа:</b> {time_str}")
            
            lines.append("")
            
            # Адрес доставки (только если НЕ самовывоз)
            if delivery_type_code != 'self-delivery':
                if 'address' in delivery and isinstance(delivery['address'], dict):
                    addr = delivery['address']
                    address_parts = []
                    
                    if addr.get('city'):
                        address_parts.append(addr['city'])
                    if addr.get('street'):
                        address_parts.append(addr['street'])
                    if addr.get('building'):
                        address_parts.append(f"д. {addr['building']}")
                    if addr.get('flat'):
                        address_parts.append(f"кв. {addr['flat']}")
                    
                    if address_parts:
                        lines.append(f"📍 <b>Адрес:</b>")
                        lines.append(f"{', '.join(address_parts)}")
                        lines.append("")
        
        return '\n'.join(lines)
    
    def _adjust_time(self, time_str: str, hours: int = -1) -> str:
        """
        Корректирует время на указанное количество часов
        
        Args:
            time_str: Время в формате "HH:MM"
            hours: Количество часов для корректировки
            
        Returns:
            Скорректированное время в формате "HH:MM"
        """
        if not time_str:
            return ""
        
        try:
            time_obj = datetime.strptime(time_str, "%H:%M")
            adjusted_time = time_obj + timedelta(hours=hours)
            return adjusted_time.strftime("%H:%M")
        except Exception as e:
            logger.warning(f"Не удалось скорректировать время '{time_str}': {e}")
            return time_str
    
    def _adjust_custom_time(self, time_str: str, hours: int = -1) -> str:
        """
        Корректирует произвольную строку времени
        
        Args:
            time_str: Строка с временем
            hours: Количество часов для корректировки
            
        Returns:
            Скорректированная строка времени
        """
        if not time_str:
            return ""
        
        try:
            time_pattern = r'\b(\d{1,2}):(\d{2})\b'
            
            def replace_time(match):
                original = match.group(0)
                adjusted = self._adjust_time(original, hours)
                return adjusted if adjusted else original
            
            result = re.sub(time_pattern, replace_time, time_str)
            return result
        except Exception as e:
            logger.warning(f"Не удалось обработать строку времени '{time_str}': {e}")
            return time_str
    
    async def send_notification_to_warehouse_admins(self, order: Dict, message: str,
                                                keyboard: InlineKeyboardMarkup,
                                                image_urls: List[str] = None) -> None:
        """Отправляет уведомление администраторам склада"""
        from aiogram.exceptions import (
            TelegramBadRequest,
            TelegramForbiddenError,
            TelegramNetworkError,
            TelegramRetryAfter
        )
        
        warehouse_code = order.get('shipmentStore')
        if not warehouse_code:
            logger.warning(f"У заказа {order.get('id')} не указан склад отгрузки")
            return
        
        target_admins = self.get_admins_for_warehouse(warehouse_code)
        if not target_admins:
            logger.warning(f"Нет администраторов для склада {warehouse_code}")
            return
        
        logger.info(f"Отправка уведомления для склада {warehouse_code} → {len(target_admins)} администраторам")
        
        for idx, (user_id, chat_id) in enumerate(target_admins):
            try:
                logger.info(f" → Отправка в чат {chat_id} (админ {user_id})")
                
                # Попытка отправки с изображениями
                if image_urls and len(image_urls) > 0:
                    try:
                        if len(image_urls) == 1:
                            # Одно изображение
                            await self.bot.send_photo(
                                chat_id=chat_id,
                                photo=image_urls[0],
                                caption=message,
                                reply_markup=keyboard,
                                parse_mode="HTML"
                            )
                        else:
                            # Несколько изображений
                            media_group = []
                            for img_idx, url in enumerate(image_urls[:10]):
                                if img_idx == 0:
                                    media_group.append(
                                        InputMediaPhoto(media=url, caption=message, parse_mode="HTML")
                                    )
                                else:
                                    media_group.append(InputMediaPhoto(media=url))
                            
                            await self.bot.send_media_group(chat_id=chat_id, media=media_group)
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text="Выберите действие:",
                                reply_markup=keyboard
                            )
                    
                    except TelegramBadRequest as e:
                        # Проблема с изображением (битая ссылка, неверный формат)
                        logger.warning(f"⚠️ Не удалось отправить изображение в чат {chat_id}: {e}")
                        logger.info(f"Отправка сообщения без изображения в чат {chat_id}")
                        
                        # Отправляем без изображения
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=message,
                            reply_markup=keyboard,
                            parse_mode="HTML"
                        )
                else:
                    # Без изображений
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                
                logger.info(f"✅ Уведомление отправлено в чат {chat_id}")
                
                # Задержка между отправками
                if idx < len(target_admins) - 1:
                    await asyncio.sleep(0.5)
            
            except TelegramForbiddenError:
                # Бот заблокирован пользователем или удалён из группы
                logger.warning(f"🚫 Бот заблокирован в чате {chat_id} (админ {user_id})")
                # Продолжаем работу, не останавливая бота
            
            except TelegramRetryAfter as e:
                # Flood control - слишком много запросов
                retry_after = e.retry_after
                logger.warning(f"⏳ Flood control для чата {chat_id}. Ожидание {retry_after} секунд")
                await asyncio.sleep(retry_after)
                
                # Повторная попытка после ожидания
                try:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                    logger.info(f"✅ Уведомление отправлено в чат {chat_id} после ожидания")
                except Exception as retry_error:
                    logger.error(f"❌ Повторная отправка в чат {chat_id} не удалась: {retry_error}")
            
            except TelegramNetworkError as e:
                # Сетевая ошибка (проблемы с интернетом, Telegram API недоступен)
                logger.error(f"🌐 Сетевая ошибка при отправке в чат {chat_id}: {e}")
                # Продолжаем работу с другими чатами
            
            except Exception as e:
                # Любые другие непредвиденные ошибки
                logger.error(f"❌ Непредвиденная ошибка при отправке в чат {chat_id}: {e}", exc_info=True)
    
    def should_refresh_cache(self) -> bool:
        """Проверяет нужно ли обновить кэш"""
        now = datetime.now()
        current_date = now.date()
        current_time = now.time()
        
        if self.last_cache_refresh_date != current_date:
            if current_time >= self.CACHE_REFRESH_TIME and current_time.hour == 0:
                return True
        
        return False
    
    def refresh_products_cache(self) -> None:
        """Обновляет кэш товаров"""
        try:
            logger.info("🔄 Начало обновления кэша товаров...")
            self.retailcrm_service._products_cache = None
            products_map = self.retailcrm_service.get_all_products()
            self.last_cache_refresh_date = datetime.now().date()
            logger.info(f"✅ Кэш товаров обновлён! Загружено товаров: {len(products_map)}")
        except Exception as e:
            logger.error(f"❌ Ошибка при обновлении кэша товаров: {e}", exc_info=True)
            self.db.log_error('cache_refresh_failed', str(e))
    
    async def check_orders_with_status(self) -> None:
        """Проверяет наличие заказов с целевым статусом и возвращённых из no-product"""
        start_time = time.time()
        
        try:
            # Получаем НОВЫЕ заказы со статусом 'otpravlen-v-sborku'
            orders = self.retailcrm_service.get_orders_by_status(self.TARGET_STATUS_CODE)
            
            # Проверяем заказы которые вернулись из no-product
            returned_from_no_product = await self._check_orders_returned_from_no_product()
            
            api_response_time = time.time() - start_time
            
            # Объединяем обе группы
            all_orders = (orders or []) + (returned_from_no_product or [])
            
            if all_orders and len(all_orders) > 0:
                # Фильтруем только новые заказы
                new_orders = [
                    order for order in all_orders
                    if not self.db.is_order_processed(order.get('id'))
                ]
                
                if new_orders:
                    for order in new_orders:
                        order_id = order.get('id')
                        order_number = order.get('number', 'N/A')
                        total_sum = order.get('totalSumm', 0)
                        warehouse_code = order.get('shipmentStore', 'N/A')
                        
                        delivery = order.get('delivery', {})
                        delivery_type = delivery.get('code', '')
                        
                        try:
                            logger.info(f"📦 Новый заказ {order_number} (ID: {order_id}) для склада {warehouse_code}")
                            
                            message = self.format_order_notification(order)
                            keyboard = self.create_order_keyboard(order_id)
                            
                            image_urls = self.retailcrm_service.get_product_images_from_order(order)
                            
                            await self.send_notification_to_warehouse_admins(order, message, keyboard, image_urls)
                            
                            self.db.save_processed_order(
                                order_id=order_id,
                                order_number=order_number,
                                status=self.TARGET_STATUS_CODE,
                                delivery_type=delivery_type,
                                total_sum=total_sum,
                                warehouse_code=warehouse_code
                            )
                            
                            logger.info(f"✅ Заказ {order_number} (ID: {order_id}) успешно обработан")
                        
                        except Exception as e:
                            logger.error(f"❌ Ошибка при обработке заказа {order_id}: {e}", exc_info=True)
                            self.db.log_error('order_processing_failed', str(e), order_id)
                    
                    logger.info(f"✅ Обработано {len(new_orders)} новых заказов")
        
        except Exception as e:
            logger.error(f"❌ Ошибка при проверке заказов: {e}", exc_info=True)
            self.db.log_error('monitoring_check_failed', str(e))
    
    async def _check_orders_returned_from_no_product(self) -> List[Dict]:
        """
        Проверяет заказы которые вернулись из 'no-product' обратно в 'otpravlen-v-sborku'
        """
        try:
            processed_orders = self.db.get_all_processed_orders()
            
            if not processed_orders:
                return []
            
            returned_orders = []
            
            for processed_order in processed_orders:
                order_id = processed_order['order_id']
                
                # БЫЛ ЛИ В NO-PRODUCT?
                if not processed_order.get('was_in_no_product'):
                    continue
                
                # УЖЕ ЛИ ВОЗВРАЩАЛСЯ?
                if processed_order.get('returned_from_no_product'):
                    continue
                
                # Получаем текущий статус
                try:
                    current_order = self.retailcrm_service.get_order_by_id(order_id)
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось получить заказ {order_id}: {e}")
                    continue
                
                if not current_order:
                    continue
                
                current_status = current_order.get('status')
                
                # ВЕРНУЛСЯ В OTPRAVLEN-V-SBORKU?
                if current_status == self.STATUS_RETURNED:
                    logger.info(f"🔄 Заказ {order_id} вернулся из no-product → {self.STATUS_RETURNED}")
                    
                    # Отмечаем что возвращался
                    self.db.mark_order_returned_from_no_product(order_id)
                    
                    # Удаляем для переправки
                    self.db.reset_order_for_renotification(order_id)
                    
                    # Логируем
                    self.db.log_error(
                        'order_returned_from_no_product',
                        f'Заказ вернулся из no-product в {self.STATUS_RETURNED}',
                        order_id
                    )
                    
                    returned_orders.append(current_order)
            
            if returned_orders:
                logger.info(f"📥 Найдено {len(returned_orders)} заказов вернулось из no-product")
            
            return returned_orders
        
        except Exception as e:
            logger.error(f"❌ Ошибка при проверке возврата из no-product: {e}", exc_info=True)
            return []
    
    async def monitor_loop(self) -> None:
        """Основной цикл мониторинга с защитой от критических ошибок"""
        
        logger.info("=" * 60)
        logger.info("🔄 МОНИТОРИНГ ЗАКАЗОВ ЗАПУЩЕН")
        logger.info("=" * 60)
        logger.info(f"📊 Администраторов: {len(self.admin_config)}")
        logger.info(f"⏱️  Интервал проверки: {self.CHECK_INTERVAL} секунд")
        logger.info(f"🔄 Автообновление кэша: каждый день в {self.CACHE_REFRESH_TIME.strftime('%H:%M')}")
        logger.info(f"🎯 Целевой статус: {self.TARGET_STATUS_CODE}")
        logger.info("=" * 60)
        
        cleanup_counter = 0
        error_counter = 0  # Счетчик ошибок подряд
        MAX_CONSECUTIVE_ERRORS = 5  # Максимум ошибок подряд перед паузой
        
        # Основной цикл мониторинга
        while self.is_running:
            try:
                # ============ ПРОВЕРКА КЭША ============
                if self.should_refresh_cache():
                    try:
                        logger.info("🔄 Начинаю обновление кэша товаров...")
                        self.refresh_products_cache()
                        logger.info("✅ Кэш товаров успешно обновлен")
                    except Exception as cache_error:
                        logger.error(f"❌ Ошибка обновления кэша: {cache_error}", exc_info=True)
                        # Продолжаем работу даже если кэш не обновился
                
                # ============ ОСНОВНАЯ ПРОВЕРКА ЗАКАЗОВ ============
                try:
                    await self.check_orders_with_status()
                    
                    # Сбрасываем счетчик ошибок при успешной проверке
                    error_counter = 0
                    
                except Exception as check_error:
                    error_counter += 1
                    logger.error(
                        f"❌ Ошибка при проверке заказов (#{error_counter}): {check_error}",
                        exc_info=True
                    )
                    
                    # Если слишком много ошибок подряд - делаем большую паузу
                    if error_counter >= MAX_CONSECUTIVE_ERRORS:
                        logger.critical(
                            f"🚨 КРИТИЧНО: {error_counter} ошибок подряд! "
                            f"Пауза на 5 минут для восстановления..."
                        )
                        await asyncio.sleep(300)  # 5 минут
                        error_counter = 0  # Сбрасываем после большой паузы
                
                # ============ ОЧИСТКА СТАРЫХ ДАННЫХ ============
                cleanup_counter += 1
                
                if cleanup_counter >= 1440:  # Раз в сутки (1440 минут)
                    try:
                        logger.info("🧹 Запуск очистки старых данных БД...")
                        deleted = self.db.remove_old_processed_orders(days=30)
                        logger.info(f"✅ Очистка завершена, удалено {deleted} записей")
                        cleanup_counter = 0
                    except Exception as cleanup_error:
                        logger.error(f"❌ Ошибка при очистке БД: {cleanup_error}", exc_info=True)
                        # Не критично, продолжаем работу
                
                # ============ ОЖИДАНИЕ ДО СЛЕДУЮЩЕЙ ПРОВЕРКИ ============
                await asyncio.sleep(self.CHECK_INTERVAL)
                
            # ============ ОБРАБОТКА СПЕЦИАЛЬНЫХ ИСКЛЮЧЕНИЙ ============
            
            except asyncio.CancelledError:
                # Graceful shutdown - получен сигнал остановки
                logger.info("⏹️  Мониторинг получил сигнал остановки (CancelledError)")
                logger.info("🛑 Корректное завершение работы мониторинга...")
                break  # Выходим из цикла
                
            except KeyboardInterrupt:
                # Пользователь остановил бота вручную
                logger.info("⏹️  Мониторинг прерван пользователем (KeyboardInterrupt)")
                logger.info("🛑 Корректное завершение работы мониторинга...")
                break  # Выходим из цикла
                
            except MemoryError:
                # Критическая нехватка памяти
                logger.critical("💥 OUT OF MEMORY! Критическая нехватка памяти!")
                logger.info("🧹 Экстренная очистка кэша...")
                
                # Очищаем все кэши для освобождения памяти
                try:
                    self.retailcrm_service._stores_cache = None
                    self.retailcrm_service._products_cache = None
                    logger.info("✅ Кэш очищен")
                except Exception as clear_error:
                    logger.error(f"❌ Не удалось очистить кэш: {clear_error}")
                
                # Большая пауза для восстановления системы
                logger.info("⏸️  Пауза на 5 минут для восстановления памяти...")
                await asyncio.sleep(300)  # 5 минут
                
                # Пробуем продолжить работу
                logger.info("🔄 Попытка возобновить мониторинг...")
                continue
                
            except SystemExit:
                # Системный выход (shutdown)
                logger.info("⏹️  Получен сигнал завершения системы (SystemExit)")
                logger.info("🛑 Корректное завершение работы мониторинга...")
                break
                
            except Exception as e:
                # Любые другие непредвиденные ошибки
                logger.error(
                    f"❌ НЕПРЕДВИДЕННАЯ ОШИБКА в цикле мониторинга: {e}",
                    exc_info=True  # Полный traceback для отладки
                )
                
                # Логируем в БД для аналитики
                try:
                    self.db.log_error('monitor_loop_unexpected_error', str(e))
                except:
                    pass  # Если даже логирование не работает - продолжаем
                
                # Пауза перед следующей попыткой
                logger.info("⏸️  Пауза 60 секунд перед следующей попыткой...")
                await asyncio.sleep(60)
                
                # ВАЖНО: продолжаем работу (не break!)
                continue
        
        # ============ ЗАВЕРШЕНИЕ РАБОТЫ ============
        logger.info("=" * 60)
        logger.info("✅ МОНИТОРИНГ ЗАКАЗОВ КОРРЕКТНО ОСТАНОВЛЕН")
        logger.info("=" * 60)
    
    async def start(self):
        """Запускает фоновую задачу мониторинга"""
        if self.is_running:
            logger.warning("Мониторинг уже запущен")
            return
        
        self.is_running = True
        self.task = asyncio.create_task(self.monitor_loop())
        logger.info("✅ Фоновая задача мониторинга запущена")
    
    async def stop(self):
        """Останавливает фоновую задачу мониторинга"""
        if not self.is_running:
            logger.warning("Мониторинг не запущен")
            return
        
        logger.info("Остановка мониторинга...")
        self.is_running = False
        
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                logger.info("Задача мониторинга отменена")
        
        logger.info("Мониторинг заказов остановлен")
    
    
