from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from database.db_service import DatabaseService
from config.settings import Settings
from keyboards.inline_keyboards import OrderKeyboards  # ← Импорт вашего класса
import logging

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "show_stats_menu")
async def handle_stats_menu(callback: CallbackQuery):
    """Показывает меню статистики"""
    keyboard = OrderKeyboards.get_stats_menu()  # ← Используем ваш класс
    
    await callback.message.edit_text(
        "📊 <b>Выберите тип статистики:</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_main")
async def handle_back_to_main(callback: CallbackQuery):
    """Возврат в главное меню"""
    keyboard = OrderKeyboards.get_main_menu()  # ← Используем ваш класс
    
    await callback.message.edit_text(
        "🤖 <b>Главное меню</b>\n\n"
        "Выберите действие:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "show_stats")
async def handle_show_stats_callback(callback: CallbackQuery):
    """Показывает общую статистику за 7 дней"""
    try:
        db = DatabaseService()
        
        # Получаем статистику
        all_stats = db.get_all_admins_stats(days=7)
        monitoring_stats = db.get_monitoring_stats(hours=24)
        db_stats = db.get_database_stats()
        admin_warehouses = Settings.get_admin_warehouses()
        
        # Формируем сообщение
        lines = []
        lines.append("📊 <b>ОБЩАЯ СТАТИСТИКА ЗА 7 ДНЕЙ</b>")
        lines.append("")
        
        # Список администраторов
        lines.append("👥 <b>Администраторы системы:</b>")
        lines.append(f"Всего: <b>{len(admin_warehouses)}</b> человек")
        lines.append("")
        
        for admin_id, warehouse_code in admin_warehouses.items():
            admin_stat = next(
                (s for s in all_stats if str(s['admin_id']) == admin_id),
                None
            )
            
            if admin_stat:
                total = admin_stat['confirmed'] + admin_stat['rejected']
                lines.append(
                    f"• ID: <code>{admin_id}</code> (Склад: {warehouse_code})\n"
                    f"  Обработано: {total} | "
                    f"✅ {admin_stat['confirmed']} | "
                    f"❌ {admin_stat['rejected']} | "
                    f"📦 {admin_stat['completed']}"
                )
            else:
                lines.append(
                    f"• ID: <code>{admin_id}</code> (Склад: {warehouse_code})\n"
                    f"  Обработано: 0 заказов"
                )
        
        lines.append("")
        lines.append("─" * 35)
        lines.append("")
        
        # Общая статистика
        if all_stats:
            total_confirmed = sum(s['confirmed'] for s in all_stats)
            total_rejected = sum(s['rejected'] for s in all_stats)
            total_completed = sum(s['completed'] for s in all_stats)
            total_orders = total_confirmed + total_rejected
            
            lines.append("📈 <b>Итого по всем администраторам:</b>")
            lines.append(f"Всего обработано: <b>{total_orders}</b> заказов")
            lines.append(f"✅ Подтверждено: <b>{total_confirmed}</b>")
            lines.append(f"❌ Отклонено: <b>{total_rejected}</b>")
            lines.append(f"📦 Завершено: <b>{total_completed}</b>")
            
            if total_orders > 0:
                confirm_rate = (total_confirmed / total_orders) * 100
                lines.append(f"📊 Процент подтверждения: <b>{confirm_rate:.1f}%</b>")
        else:
            lines.append("📈 <b>Статистика:</b>")
            lines.append("Нет обработанных заказов за последние 7 дней")
        
        lines.append("")
        lines.append("─" * 35)
        lines.append("")
        
        # Мониторинг
        lines.append("🔄 <b>Мониторинг за 24 часа:</b>")
        lines.append(f"Проверок выполнено: <b>{monitoring_stats['total_checks']}</b>")
        lines.append(f"✅ Успешных: <b>{monitoring_stats['successful_checks']}</b>")
        
        if monitoring_stats['failed_checks'] > 0:
            lines.append(f"❌ Ошибок: <b>{monitoring_stats['failed_checks']}</b>")
        
        lines.append(f"Найдено заказов: <b>{monitoring_stats['orders_found']}</b>")
        lines.append(f"Отправлено уведомлений: <b>{monitoring_stats['orders_notified']}</b>")
        lines.append(f"Среднее время API: <b>{monitoring_stats['avg_response_time']}</b> сек")
        
        lines.append("")
        lines.append("─" * 35)
        lines.append("")
        
        # База данных
        lines.append("💾 <b>База данных:</b>")
        lines.append(f"Размер БД: <b>{db_stats['db_size_mb']}</b> МБ")
        lines.append(f"Обработанных заказов: <b>{db_stats['processed_orders_count']}</b>")
        lines.append(f"Записей действий: <b>{db_stats['order_actions_count']}</b>")
        lines.append(f"Записей мониторинга: <b>{db_stats['monitoring_checks_count']}</b>")
        
        formatted_text = '\n'.join(lines)
        
        keyboard = OrderKeyboards.get_back_to_stats_button()  # ← Используем ваш класс
        
        await callback.message.edit_text(formatted_text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при формировании статистики: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при получении статистики", show_alert=True)


@router.callback_query(F.data == "show_my_stats")
async def handle_show_my_stats_callback(callback: CallbackQuery):
    """Показывает личную статистику администратора"""
    try:
        admin_id = callback.from_user.id
        db = DatabaseService()
        
        stats_7d = db.get_admin_stats(admin_id, days=7)
        stats_30d = db.get_admin_stats(admin_id, days=30)
        
        admin_warehouses = Settings.get_admin_warehouses()
        warehouse_code = admin_warehouses.get(str(admin_id), "N/A")
        
        lines = []
        lines.append("👤 <b>ВАША СТАТИСТИКА</b>")
        lines.append("")
        lines.append(f"🆔 Ваш ID: <code>{admin_id}</code>")
        lines.append(f"🏢 Ваш склад: <b>{warehouse_code}</b>")
        lines.append("")
        lines.append("─" * 35)
        lines.append("")
        
        # За 7 дней
        lines.append("📅 <b>За последние 7 дней:</b>")
        total_7d = stats_7d['confirmed'] + stats_7d['rejected']
        
        if total_7d > 0:
            lines.append(f"Всего обработано: <b>{total_7d}</b> заказов")
            lines.append(f"✅ Подтверждено: <b>{stats_7d['confirmed']}</b>")
            lines.append(f"❌ Отклонено: <b>{stats_7d['rejected']}</b>")
            lines.append(f"📦 Завершено: <b>{stats_7d['completed']}</b>")
            
            confirm_rate = (stats_7d['confirmed'] / total_7d) * 100
            lines.append(f"📊 Процент подтверждения: <b>{confirm_rate:.1f}%</b>")
        else:
            lines.append("Нет обработанных заказов")
        
        lines.append("")
        lines.append("─" * 35)
        lines.append("")
        
        # За 30 дней
        lines.append("📅 <b>За последние 30 дней:</b>")
        total_30d = stats_30d['confirmed'] + stats_30d['rejected']
        
        if total_30d > 0:
            lines.append(f"Всего обработано: <b>{total_30d}</b> заказов")
            lines.append(f"✅ Подтверждено: <b>{stats_30d['confirmed']}</b>")
            lines.append(f"❌ Отклонено: <b>{stats_30d['rejected']}</b>")
            lines.append(f"📦 Завершено: <b>{stats_30d['completed']}</b>")
            
            confirm_rate = (stats_30d['confirmed'] / total_30d) * 100
            lines.append(f"📊 Процент подтверждения: <b>{confirm_rate:.1f}%</b>")
        else:
            lines.append("Нет обработанных заказов")
        
        formatted_text = '\n'.join(lines)
        
        keyboard = OrderKeyboards.get_back_to_stats_button()  # ← Используем ваш класс
        
        await callback.message.edit_text(formatted_text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при формировании личной статистики: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при получении статистики", show_alert=True)


@router.message(Command("stats"))
async def handle_stats_command(message: Message):
    """Обработка команды /stats"""
    keyboard = OrderKeyboards.get_stats_menu()
    
    await message.answer(
        "📊 <b>Выберите тип статистики:</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.message(Command("my_stats"))
async def handle_my_stats_command(message: Message):
    """Обработка команды /my_stats"""
    try:
        admin_id = message.from_user.id
        db = DatabaseService()
        
        stats_7d = db.get_admin_stats(admin_id, days=7)
        stats_30d = db.get_admin_stats(admin_id, days=30)
        
        admin_warehouses = Settings.get_admin_warehouses()
        warehouse_code = admin_warehouses.get(str(admin_id), "N/A")
        
        lines = []
        lines.append("👤 <b>ВАША СТАТИСТИКА</b>")
        lines.append("")
        lines.append(f"🆔 Ваш ID: <code>{admin_id}</code>")
        lines.append(f"🏢 Ваш склад: <b>{warehouse_code}</b>")
        lines.append("")
        lines.append("─" * 35)
        lines.append("")
        
        lines.append("📅 <b>За последние 7 дней:</b>")
        total_7d = stats_7d['confirmed'] + stats_7d['rejected']
        
        if total_7d > 0:
            lines.append(f"Всего обработано: <b>{total_7d}</b> заказов")
            lines.append(f"✅ Подтверждено: <b>{stats_7d['confirmed']}</b>")
            lines.append(f"❌ Отклонено: <b>{stats_7d['rejected']}</b>")
            lines.append(f"📦 Завершено: <b>{stats_7d['completed']}</b>")
            
            confirm_rate = (stats_7d['confirmed'] / total_7d) * 100
            lines.append(f"📊 Процент подтверждения: <b>{confirm_rate:.1f}%</b>")
        else:
            lines.append("Нет обработанных заказов")
        
        lines.append("")
        lines.append("─" * 35)
        lines.append("")
        
        lines.append("📅 <b>За последние 30 дней:</b>")
        total_30d = stats_30d['confirmed'] + stats_30d['rejected']
        
        if total_30d > 0:
            lines.append(f"Всего обработано: <b>{total_30d}</b> заказов")
            lines.append(f"✅ Подтверждено: <b>{stats_30d['confirmed']}</b>")
            lines.append(f"❌ Отклонено: <b>{stats_30d['rejected']}</b>")
            lines.append(f"📦 Завершено: <b>{stats_30d['completed']}</b>")
            
            confirm_rate = (stats_30d['confirmed'] / total_30d) * 100
            lines.append(f"📊 Процент подтверждения: <b>{confirm_rate:.1f}%</b>")
        else:
            lines.append("Нет обработанных заказов")
        
        formatted_text = '\n'.join(lines)
        
        await message.answer(formatted_text, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка при формировании личной статистики: {e}", exc_info=True)
        await message.answer("❌ Ошибка при получении статистики")
