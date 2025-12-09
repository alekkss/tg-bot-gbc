import os
from typing import List, Dict, Tuple
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Класс для управления конфигурацией бота"""
    
    @staticmethod
    def get_bot_token() -> str:
        """Получает токен бота из переменных окружения"""
        token = os.getenv("BOT_TOKEN")
        if not token:
            raise ValueError("BOT_TOKEN не найден в переменных окружения")
        return token
    
    @staticmethod
    def get_retailcrm_api_key() -> str:
        """Получает API ключ RetailCRM"""
        api_key = os.getenv("RETAILCRM_API_KEY")
        if not api_key:
            raise ValueError("RETAILCRM_API_KEY не найден в переменных окружения")
        return api_key
    
    @staticmethod
    def get_retailcrm_domain() -> str:
        """Получает домен RetailCRM"""
        domain = os.getenv("RETAILCRM_DOMAIN")
        if not domain:
            raise ValueError("RETAILCRM_DOMAIN не найден в переменных окружения")
        return domain
    
    @staticmethod
    def get_admin_chat_id() -> str:
        """Получает ID чата администратора (для обратной совместимости)"""
        chat_ids = Settings.get_admin_chat_ids()
        return chat_ids[0] if chat_ids else ""
    
    @staticmethod
    def get_admin_chat_ids() -> List[str]:
        """Получает список ID чатов всех администраторов"""
        admin_warehouses = Settings.get_admin_warehouses()
        return list(admin_warehouses.keys())
    
    @staticmethod
    def get_admin_warehouses() -> Dict[str, str]:
        """
        Получает словарь {user_id: warehouse_code}
        Для обратной совместимости
        """
        full_config = Settings.get_admin_full_config()
        return {user_id: info['warehouse'] for user_id, info in full_config.items()}
    
    @staticmethod
    def get_admin_full_config() -> Dict[str, Dict[str, str]]:
        """
        НОВЫЙ МЕТОД: Получает полную конфигурацию администраторов
        Returns:
            {
                "436816068": {
                    "warehouse": "20",
                    "chat_id": "-4839842748"
                },
                "6787250467": {
                    "warehouse": "25",
                    "chat_id": "6787250467"
                }
            }
        """
        admin_warehouses_str = os.getenv("ADMIN_WAREHOUSES")
        if not admin_warehouses_str:
            raise ValueError("ADMIN_WAREHOUSES не найден в переменных окружения")
        
        # Проверка на пустую строку после получения
        admin_warehouses_str = admin_warehouses_str.strip()
        if not admin_warehouses_str:
            raise ValueError("ADMIN_WAREHOUSES пуст")
        
        admin_config = {}
        
        # Разбираем строку: "436816068:20:-4839842748,6787250467:25:6787250467"
        pairs = [pair.strip() for pair in admin_warehouses_str.split(",") if pair.strip()]
        
        if not pairs:
            raise ValueError("ADMIN_WAREHOUSES не содержит валидных пар данных")
        
        for pair in pairs:
            parts = pair.split(":")
            
            # Поддерживаем два формата:
            # 1. USER_ID:WAREHOUSE_CODE (старый формат)
            # 2. USER_ID:WAREHOUSE_CODE:CHAT_ID (новый формат)
            if len(parts) == 2:
                # Старый формат: USER_ID:WAREHOUSE_CODE
                user_id, warehouse_code = parts
                chat_id = user_id  # По умолчанию отправляем пользователю
            elif len(parts) == 3:
                # Новый формат: USER_ID:WAREHOUSE_CODE:CHAT_ID
                user_id, warehouse_code, chat_id = parts
            else:
                raise ValueError(
                    f"Неправильный формат ADMIN_WAREHOUSES: '{pair}'. "
                    f"Ожидается USER_ID:WAREHOUSE_CODE или USER_ID:WAREHOUSE_CODE:CHAT_ID"
                )
            
            # Критическая проверка: убираем пробелы и проверяем на пустоту
            user_id = user_id.strip()
            warehouse_code = warehouse_code.strip()
            chat_id = chat_id.strip()
            
            # НОВАЯ ПРОВЕРКА: все значения должны быть непустыми
            if not user_id:
                raise ValueError(f"Пустой user_id в паре: '{pair}'")
            if not warehouse_code:
                raise ValueError(f"Пустой warehouse_code в паре: '{pair}'")
            if not chat_id:
                raise ValueError(f"Пустой chat_id в паре: '{pair}'")
            
            # Проверка на валидность ID (должны содержать только цифры и опционально минус в начале)
            if not user_id.lstrip('-').isdigit():
                raise ValueError(f"Невалидный user_id '{user_id}' в паре: '{pair}'. Ожидается числовой ID")
            if not chat_id.lstrip('-').isdigit():
                raise ValueError(f"Невалидный chat_id '{chat_id}' в паре: '{pair}'. Ожидается числовой ID")
            
            admin_config[user_id] = {
                "warehouse": warehouse_code,
                "chat_id": chat_id
            }
        
        # Финальная проверка: должен быть хотя бы один администратор
        if not admin_config:
            raise ValueError("ADMIN_WAREHOUSES не содержит валидных администраторов")
        
        return admin_config
    
    @staticmethod
    def get_warehouse_for_admin(user_id: str) -> str:
        """Получает код склада для конкретного администратора"""
        full_config = Settings.get_admin_full_config()
        return full_config.get(user_id, {}).get("warehouse", "")
    
    @staticmethod
    def get_chat_id_for_admin(user_id: str) -> str:
        """
        НОВЫЙ МЕТОД: Получает ID чата для уведомлений конкретного администратора
        """
        full_config = Settings.get_admin_full_config()
        return full_config.get(user_id, {}).get("chat_id", user_id)
    
    # ============ REDIS НАСТРОЙКИ ============
    
    @staticmethod
    def get_redis_host() -> str:
        """Redis хост"""
        return os.getenv('REDIS_HOST', 'localhost')
    
    @staticmethod
    def get_redis_port() -> int:
        """Redis порт"""
        return int(os.getenv('REDIS_PORT', '6379'))
    
    @staticmethod
    def get_redis_db() -> int:
        """Redis database number"""
        return int(os.getenv('REDIS_DB', '0'))
    
    # ============ RATE LIMITING НАСТРОЙКИ ============
    
    @staticmethod
    def get_rate_limit_button_clicks() -> int:
        """Максимум кликов по кнопкам в минуту"""
        return int(os.getenv('RATE_LIMIT_BUTTON_CLICKS', '10'))
    
    @staticmethod
    def get_rate_limit_confirm_order() -> int:
        """Максимум подтверждений заказа в минуту"""
        return int(os.getenv('RATE_LIMIT_CONFIRM_ORDER', '5'))
    
    @staticmethod
    def get_rate_limit_window() -> int:
        """Окно времени для rate limiting (секунды)"""
        return int(os.getenv('RATE_LIMIT_WINDOW', '60'))
