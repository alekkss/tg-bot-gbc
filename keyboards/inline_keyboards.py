from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


class OrderKeyboards:
    """Класс для создания клавиатур, связанных с заказами"""
    
    @staticmethod
    def get_main_menu() -> InlineKeyboardMarkup:
        """Создаёт главное меню с кнопками"""
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔍 Найти заказ", callback_data="find_order")],
                [InlineKeyboardButton(text="📋 Вывести все доступные статусы", callback_data="show_statuses")],
                [InlineKeyboardButton(text="📊 Статистика", callback_data="show_stats_menu")]  # ← НОВАЯ КНОПКА
            ]
        )
        return keyboard
    
    @staticmethod
    def get_stats_menu() -> InlineKeyboardMarkup:
        """Создаёт меню выбора статистики"""
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📈 Общая статистика", callback_data="show_stats")],
                [InlineKeyboardButton(text="👤 Моя статистика", callback_data="show_my_stats")],
                [InlineKeyboardButton(text="« Назад", callback_data="back_to_main")]
            ]
        )
        return keyboard
    
    @staticmethod
    def get_back_to_stats_button() -> InlineKeyboardMarkup:
        """Кнопка возврата к меню статистики"""
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад к статистике", callback_data="show_stats_menu")]
            ]
        )
        return keyboard
