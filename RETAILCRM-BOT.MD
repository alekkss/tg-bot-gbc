# RETAILCRM-BOT.MD

Telegram-бот для мониторинга и управления заказами из RetailCRM (цветочный бизнес). Автоматически уведомляет администраторов о новых заказах, позволяет подтверждать/отклонять через кнопки, ведёт статистику и логирует действия с учётом типов доставки (самовывоз/курьер).

## Архитектура

- **Bot Framework**: aiogram 3.x (async)
- **База данных**: SQLite (bot_data.db) WAL mode
- **AI Integration**: Отсутствует
- **File Processing**: Отсутствует
- **State Management**: Нет FSM (callback-based)
- **Solid принципы**

## Ключевые директории

```
# Корень проекта
├── main.py # Точка входа, диспетчер, middleware
├── bot_service.py # Отправка уведомлений
├── handlers/ # Обработчики Telegram
│ ├── order_callback_handler.py # confirm_order, picked_up, discuss_replacement
│ ├── status_handler.py # Список статусов RetailCRM
│ ├── stats_handler.py # Статистика админов
│ ├── start_handler.py # /start
│ ├── get_chat_id_handler.py # Регистрация chat_id
│ └── order_handler.py # Обработка сообщений/фото
├── services/ # Бизнес-логика
│ ├── retailcrm_service.py # RetailCRM API клиент
│ ├── order_monitor_service.py # Фоновая проверка заказов
│ ├── order_formatter_service.py # Форматирование заказов
│ ├── status_formatter_service.py # Форматирование статусов
│ ├── rate_limiter.py # Redis rate limiting
│ └── bot_service.py # Отправка уведомлений
├── database/
│ └── db_service.py # SQLite ORM + миграции
├── config/
│ └── settings.py # API ключи, статусы
├── keyboards/
│ └── inline_keyboards.py # Inline клавиатуры
└── middleware/
    └── auth_middleware.py # Авторизация админов
```

## Стандарты кодирования

### Основные принципы
- **SOLID**: Да (handlers ↔ services ↔ database)
- **Async/Await**: Да (все IO операции)
- **Type Hints**: Да (полная типизация)
- **Logging**: Структурированное через logger

### Конвенции именования
- Классы: `PascalCase` (DatabaseService, RetailCRMService)
- Функции: `snake_case` (parse_callback_data, format_order_info)
- Константы: `UPPER_SNAKE_CASE` (STATUS_TRANSLATION)
- Private методы: `_leading_underscore` (_init_database)

### Обработка ошибок
```python
try:
    # Основная логика
    conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
except sqlite3.OperationalError as db_error:
    if "database is locked" in str(db_error):
        logger.error(f"❌ КРИТИЧНО: database is locked! Ошибка: {db_error}", exc_info=True)
    else:
        logger.error(f"❌ Ошибка БД: {db_error}", exc_info=True)
    conn.rollback()
    raise
```

## Ключевые компоненты

### 1. Схемы статусов (Settings)
- Хранятся в `settings.py`
- Настраиваемые коды статусов RetailCRM
- Разная логика для самовывоза/доставки

### 2. Rate Limiting (3 уровня)
1. Redis-based (rate_limiter.py)
2. 5 подтверждений/мин, 10 других действий/мин
3. Показывает remaining_time

### 3. Типы доставки
- **Разделитель**: self-delivery vs курьер
- **Самовывоз**: confirm_order → picked_up → complete
- **Доставка**: confirm_order → manual "Букет готов" → курьер

### 4. Специальная обработка
- **Фото букета**: После confirm_order
- **Фото чека**: После picked_up/completed
- **Склады**: Привязка админов к warehouse_code

## Формат данных

### Обязательные поля заказа
```json
{
"column_1": "id", # RetailCRM order_id
"column_2": "number", # Номер заказа
"column_3": "status", # Текущий статус
"description": "Заказ из RetailCRM"
}
```

### Исключённые поля
- managerComment (слишком длинный)
- custom fields (не используются)

## База данных

### Таблицы
**processed_orders** # Обработанные заказы (order_id UNIQUE)
- was_in_no_product, bouquet_ready_notified
- delivery_type (self-delivery)

**order_actions** # Лог действий админов
**admin_stats** # Ежедневная статистика (confirmed/rejected/completed)
**monitoring_checks** # Метрики мониторинга
**error_log** # Логи ошибок

### Миграции
- Автоматические через `DatabaseService._init_database()`
- WAL mode + индексы
- Cleanup старых данных (30 дней)

## AI Integration
- **Отсутствует**
- Все решения rule-based
- Логика статусов в settings.py

## Тестирование

### Ручное тестирование
- Запуск мониторинга → уведомление о новом заказе
- Подтверждение заказа → смена статуса в RetailCRM
- Проверка логов действий и статистики

### Debug режим
```bash
export LOG_LEVEL=DEBUG
python main.py
```

## Deployment

### Требования
Python 3.9+
```
aiogram==3.x
redis
requests
sqlite3 (built-in)
```

### Запуск
```bash
python main.py
```

### Переменные окружения
```
TELEGRAM_BOT_TOKEN=xxx
RETAILCRM_DOMAIN=xxx.retailcrm.ru
RETAILCRM_API_KEY=xxx
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```

## Roadmap & Known Issues

### TODO
- [ ] Добавить reject_order handler
- [ ] Webhook вместо polling
- [ ] Docker compose (Redis + bot)
- [ ] Pytest для сервисов

### Ограничения
- SQLite WAL mode (не thread-safe без timeout=30s)
- Rate limits RetailCRM API
- Telegram 4096 символов/сообщение

## Важные предостережения

### НЕ изменять без обсуждения
- Логику статусов в settings.py
- Rate limits (5/мин подтверждения)
- Формат callback_data (`action:order_id`)

### Критичные зависимости
- Порядок: мониторинг → уведомление → confirm → photo → complete
- Redis должен быть доступен для rate_limiter
- database is locked → timeout=30s критично

## Типичные сценарии работы

### Добавление нового статуса
1. Добавить в settings.py (get_status_xxx())
2. Обновить STATUS_TRANSLATION в order_formatter_service.py
3. Добавить handler в order_callback_handler.py

### Добавление нового склада
1. Новый admin_id в auth_middleware.py
2. Привязка warehouse_code в БД
3. Тестирование уведомлений
