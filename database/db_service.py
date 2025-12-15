import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


class DatabaseService:
    """Сервис для работы с базой данных SQLite"""
    
    def __init__(self, db_path: str = "bot_data.db"):
        self.db_path = db_path
        self._init_database()
        logger.info(f"База данных инициализирована: {db_path}")
    
    @contextmanager
    def get_connection(self):
        """
        Контекстный менеджер для работы с соединением с защитой от database is locked
        
        Параметры подобраны для оптимального баланса между parallelism и стабильностью:
        - timeout=30.0: ждет до 30 секунд если БД заблокирована
        - check_same_thread=False: разрешает работу из разных потоков/asyncio
        - WAL mode: Write-Ahead Logging для лучшего параллелизма (SELECT может работать во время WRITE)
        """
        conn = None
        try:
            # Подключаемся с таймаутом и разрешением многопоточности
            conn = sqlite3.connect(
                self.db_path,
                timeout=30.0,  # ← Ключевой параметр! Ждет до 30 сек вместо ошибки
                check_same_thread=False  # ← Разрешает работу из asyncio и других потоков
            )
            
            conn.row_factory = sqlite3.Row
            
            # Включаем WAL mode для лучшего параллелизма
            # WAL = Write-Ahead Logging, позволяет читать БД пока идет запись
            conn.execute("PRAGMA journal_mode=WAL")
            
            # Настраиваем дополнительные параметры для оптимизации
            conn.execute("PRAGMA synchronous=NORMAL")  # Баланс между скоростью и безопасностью
            conn.execute("PRAGMA busy_timeout=30000")  # Явный таймаут в миллисекундах
            
            yield conn
            
            # Гарантируем сохранение если не было явного commit
            if conn:
                conn.commit()
        
        except sqlite3.OperationalError as db_error:
            # Специфичная обработка ошибок БД
            if "database is locked" in str(db_error):
                logger.error(
                    f"❌ КРИТИЧНО: database is locked! "
                    f"Вероятно перегруженная БД или конфликт операций. "
                    f"Ошибка: {db_error}",
                    exc_info=True
                )
            else:
                logger.error(f"❌ Ошибка БД: {db_error}", exc_info=True)
            
            # Пробуем откатить если есть активная транзакция
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            
            raise  # Пробрасываем ошибку выше для обработки
        
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при работе с БД: {e}", exc_info=True)
            
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            
            raise
        
        finally:
            # Гарантируем закрытие соединения
            if conn:
                try:
                    conn.close()
                except Exception as close_error:
                    logger.warning(f"⚠️ Ошибка при закрытии соединения: {close_error}")
    
    def _init_database(self):
        """Инициализирует структуру базы данных"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица обработанных заказов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER UNIQUE NOT NULL,
                    order_number TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_sum REAL,
                    customer_name TEXT,
                    warehouse_code TEXT,
                    delivery_type TEXT,
                    was_in_no_product BOOLEAN DEFAULT 0,
                    returned_from_no_product BOOLEAN DEFAULT 0,
                    bouquet_ready_notified BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Индексы для быстрого поиска
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_order_id
                ON processed_orders(order_id)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_notified_at
                ON processed_orders(notified_at)
            """)
            
            # Таблица действий администраторов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    admin_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    comment TEXT,
                    action_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_order_actions_order_id
                ON order_actions(order_id)
            """)
            
            # Таблица статистики администраторов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS admin_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    date DATE NOT NULL,
                    confirmed_count INTEGER DEFAULT 0,
                    rejected_count INTEGER DEFAULT 0,
                    completed_count INTEGER DEFAULT 0,
                    UNIQUE(admin_id, date)
                )
            """)
            
            # Таблица проверок мониторинга
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS monitoring_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    check_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    orders_found INTEGER DEFAULT 0,
                    orders_notified INTEGER DEFAULT 0,
                    api_response_time REAL,
                    success BOOLEAN DEFAULT 1,
                    error_message TEXT
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_monitoring_check_time
                ON monitoring_checks(check_time)
            """)
            
            # Таблица логов ошибок
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS error_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    error_type TEXT NOT NULL,
                    error_message TEXT,
                    order_id INTEGER,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_error_timestamp
                ON error_log(timestamp)
            """)
            
            conn.commit()
    
    def is_order_processed(self, order_id: int) -> bool:
        """Проверяет был ли заказ уже обработан"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM processed_orders WHERE order_id = ?",
                (order_id,)
            )
            count = cursor.fetchone()[0]
            return count > 0
    
    def save_processed_order(self, order_id: int, order_number: str, status: str,
                        delivery_type: str = None, **kwargs) -> bool:
        """
        Сохраняет информацию об обработанном заказе
        
        Args:
            order_id: ID заказа
            order_number: Номер заказа
            status: Статус заказа
            delivery_type: Тип доставки ('self-delivery' или другое)
            **kwargs: Дополнительные параметры
        
        Returns:
            True если успешно, False если ошибка
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO processed_orders 
                    (order_id, order_number, status, total_sum, customer_name, 
                    warehouse_code, delivery_type, was_in_no_product, returned_from_no_product, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, CURRENT_TIMESTAMP)
                """, (
                    order_id,
                    order_number,
                    status,
                    kwargs.get('total_sum'),
                    kwargs.get('customer_name'),
                    kwargs.get('warehouse_code'),
                    delivery_type
                ))
                
                conn.commit()
                logger.info(f"✅ Заказ {order_number} (ID: {order_id}) сохранён в БД")
                return True
        except Exception as e:
            logger.error(f"❌ Ошибка при сохранении заказа {order_id}: {e}")
            return False
    
    def get_order_delivery_type(self, order_id: int) -> Optional[str]:
        """Получает тип доставки для заказа из БД"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT delivery_type FROM processed_orders WHERE order_id = ?",
                    (order_id,)
                )
                result = cursor.fetchone()
                return result['delivery_type'] if result else None
        except Exception as e:
            logger.error(f"Ошибка при получении типа доставки для заказа {order_id}: {e}")
            return None
    
    def add_processed_order(self, order_id: int, order_number: str,
                           status: str, total_sum: float = None):
        """Добавляет заказ в список обработанных (устаревший метод, используйте save_processed_order)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO processed_orders (order_id, order_number, status, total_sum)
                    VALUES (?, ?, ?, ?)
                """, (order_id, order_number, status, total_sum))
                conn.commit()
                logger.info(f"Заказ {order_number} (ID: {order_id}) добавлен в обработанные")
            except sqlite3.IntegrityError:
                logger.warning(f"Заказ {order_id} уже существует в БД")
    
    def log_order_action(self, order_id: int, admin_id: int,
                        action: str, comment: str = None):
        """
        Логирует действие администратора с заказом
        
        Args:
            order_id: ID заказа
            admin_id: ID администратора Telegram
            action: Тип действия ('confirmed', 'bouquet_ready', 'sent_to_delivery', 'completed', etc.)
            comment: Комментарий к действию
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO order_actions (order_id, admin_id, action, comment, action_time)
                VALUES (?, ?, ?, ?, ?)
            """, (order_id, admin_id, action, comment, datetime.now()))
            conn.commit()
            
            # Обновляем статистику администратора
            self._update_admin_stats(admin_id, action)
            logger.info(f"Действие '{action}' для заказа {order_id} от админа {admin_id}")
    
    def _update_admin_stats(self, admin_id: int, action: str):
        """Обновляет статистику администратора"""
        today = datetime.now().date()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Проверяем есть ли запись за сегодня
            cursor.execute("""
                SELECT id FROM admin_stats
                WHERE admin_id = ? AND date = ?
            """, (admin_id, today))
            
            existing = cursor.fetchone()
            
            if existing:
                # Обновляем существующую запись
                if action == 'confirmed':
                    cursor.execute("""
                        UPDATE admin_stats
                        SET confirmed_count = confirmed_count + 1
                        WHERE admin_id = ? AND date = ?
                    """, (admin_id, today))
                elif action == 'rejected':
                    cursor.execute("""
                        UPDATE admin_stats
                        SET rejected_count = rejected_count + 1
                        WHERE admin_id = ? AND date = ?
                    """, (admin_id, today))
                elif action == 'completed':
                    cursor.execute("""
                        UPDATE admin_stats
                        SET completed_count = completed_count + 1
                        WHERE admin_id = ? AND date = ?
                    """, (admin_id, today))
            else:
                # Создаём новую запись
                confirmed = 1 if action == 'confirmed' else 0
                rejected = 1 if action == 'rejected' else 0
                completed = 1 if action == 'completed' else 0
                
                cursor.execute("""
                    INSERT INTO admin_stats
                    (admin_id, date, confirmed_count, rejected_count, completed_count)
                    VALUES (?, ?, ?, ?, ?)
                """, (admin_id, today, confirmed, rejected, completed))
            
            conn.commit()
    
    def get_order_actions(self, order_id: int) -> List[Dict]:
        """Получает все действия по заказу"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT order_id, admin_id, action, comment, action_time
                FROM order_actions
                WHERE order_id = ?
                ORDER BY action_time DESC
            """, (order_id,))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_admin_stats(self, admin_id: int, days: int = 7) -> Dict:
        """
        Получает статистику администратора за указанное количество дней
        """
        start_date = datetime.now().date() - timedelta(days=days)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    SUM(confirmed_count) as total_confirmed,
                    SUM(rejected_count) as total_rejected,
                    SUM(completed_count) as total_completed
                FROM admin_stats
                WHERE admin_id = ? AND date >= ?
            """, (admin_id, start_date))
            
            row = cursor.fetchone()
            
            return {
                'admin_id': admin_id,
                'period_days': days,
                'confirmed': row['total_confirmed'] or 0,
                'rejected': row['total_rejected'] or 0,
                'completed': row['total_completed'] or 0,
                'total': (row['total_confirmed'] or 0) + (row['total_rejected'] or 0)
            }
    
    def get_all_admins_stats(self, days: int = 7) -> List[Dict]:
        """Получает статистику всех администраторов"""
        start_date = datetime.now().date() - timedelta(days=days)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    admin_id,
                    SUM(confirmed_count) as total_confirmed,
                    SUM(rejected_count) as total_rejected,
                    SUM(completed_count) as total_completed
                FROM admin_stats
                WHERE date >= ?
                GROUP BY admin_id
                ORDER BY (SUM(confirmed_count) + SUM(rejected_count)) DESC
            """, (start_date,))
            
            rows = cursor.fetchall()
            
            return [
                {
                    'admin_id': row['admin_id'],
                    'confirmed': row['total_confirmed'] or 0,
                    'rejected': row['total_rejected'] or 0,
                    'completed': row['total_completed'] or 0,
                    'total': (row['total_confirmed'] or 0) + (row['total_rejected'] or 0)
                }
                for row in rows
            ]
    
    def log_monitoring_check(self, orders_found: int, orders_notified: int,
                            api_response_time: float, success: bool = True,
                            error_message: str = None):
        """Логирует проверку мониторинга"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO monitoring_checks
                (orders_found, orders_notified, api_response_time, success, error_message)
                VALUES (?, ?, ?, ?, ?)
            """, (orders_found, orders_notified, api_response_time, success, error_message))
            conn.commit()
    
    def get_monitoring_stats(self, hours: int = 24) -> Dict:
        """Получает статистику мониторинга за указанное количество часов"""
        start_time = datetime.now() - timedelta(hours=hours)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_checks,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_checks,
                    SUM(orders_found) as total_orders_found,
                    SUM(orders_notified) as total_orders_notified,
                    AVG(api_response_time) as avg_response_time,
                    MAX(api_response_time) as max_response_time
                FROM monitoring_checks
                WHERE check_time >= ?
            """, (start_time,))
            
            row = cursor.fetchone()
            
            return {
                'period_hours': hours,
                'total_checks': row['total_checks'] or 0,
                'successful_checks': row['successful_checks'] or 0,
                'failed_checks': (row['total_checks'] or 0) - (row['successful_checks'] or 0),
                'orders_found': row['total_orders_found'] or 0,
                'orders_notified': row['total_orders_notified'] or 0,
                'avg_response_time': round(row['avg_response_time'] or 0, 3),
                'max_response_time': round(row['max_response_time'] or 0, 3)
            }
    
    def log_error(self, error_type: str, error_message: str, order_id: int = None):
        """Логирует ошибку в базу данных"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO error_log (error_type, error_message, order_id)
                VALUES (?, ?, ?)
            """, (error_type, error_message, order_id))
            conn.commit()
    
    def get_recent_errors(self, hours: int = 24, limit: int = 50) -> List[Dict]:
        """Получает последние ошибки"""
        start_time = datetime.now() - timedelta(hours=hours)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT error_type, error_message, order_id, timestamp
                FROM error_log
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (start_time, limit))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def remove_old_processed_orders(self, days: int = 30) -> int:
        """
        Удаляет старые обработанные заказы
        
        Args:
            days: Удалить заказы старше указанного количества дней
            
        Returns:
            Количество удалённых записей
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM processed_orders
                WHERE notified_at < ?
            """, (cutoff_date,))
            
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"Удалено {deleted_count} старых заказов (старше {days} дней)")
            return deleted_count
    
    def remove_old_monitoring_checks(self, days: int = 7) -> int:
        """Удаляет старые записи мониторинга"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM monitoring_checks
                WHERE check_time < ?
            """, (cutoff_date,))
            
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"Удалено {deleted_count} старых записей мониторинга")
            return deleted_count
    
    def remove_old_errors(self, days: int = 30) -> int:
        """Удаляет старые логи ошибок"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM error_log
                WHERE timestamp < ?
            """, (cutoff_date,))
            
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"Удалено {deleted_count} старых логов ошибок")
            return deleted_count
    
    def get_database_stats(self) -> Dict:
        """Получает общую статистику базы данных"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            stats = {}
            
            # Количество записей в каждой таблице
            tables = [
                'processed_orders',
                'order_actions',
                'admin_stats',
                'monitoring_checks',
                'error_log'
            ]
            
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[f'{table}_count'] = cursor.fetchone()[0]
            
            # Размер базы данных
            import os
            if os.path.exists(self.db_path):
                stats['db_size_mb'] = round(os.path.getsize(self.db_path) / (1024 * 1024), 2)
            else:
                stats['db_size_mb'] = 0
            
            return stats
    
    def reset_order_status(self, order_id: int) -> bool:
        """
        Удаляет заказ из таблицы обработанных (чтобы пересказать уведомление)
        Используется когда заказ вернулся из 'no-product' в 'otpravlen-v-sborku'
        
        Args:
            order_id: ID заказа
            
        Returns:
            True если удалось, False если ошибка
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM processed_orders WHERE order_id = ?",
                    (order_id,)
                )
                conn.commit()
                
                if cursor.rowcount > 0:
                    logger.info(f"✅ Заказ {order_id} удалён из обработанных (для переоправки уведомления)")
                    return True
                else:
                    logger.warning(f"⚠️ Заказ {order_id} не найден в обработанных")
                    return False
        except Exception as e:
            logger.error(f"❌ Ошибка при удалении заказа {order_id}: {e}")
            return False
    
    def get_all_processed_orders(self) -> List[Dict]:
        """Получает все обработанные заказы из БД"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT order_id, order_number, status, delivery_type, warehouse_code,
                           was_in_no_product, returned_from_no_product, 
                           bouquet_ready_notified, created_at
                    FROM processed_orders
                    ORDER BY created_at DESC
                """)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"❌ Ошибка при получении обработанных заказов: {e}")
            return []
        
    def mark_order_in_no_product(self, order_id: int) -> bool:
        """Отмечает что заказ был в статусе no-product"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE processed_orders
                    SET was_in_no_product = 1, updated_at = CURRENT_TIMESTAMP
                    WHERE order_id = ?
                """, (order_id,))
                conn.commit()
                logger.info(f"✅ Заказ {order_id} отмечен: был в no-product")
                return True
        except Exception as e:
            logger.error(f"Ошибка при отметке заказа в no-product: {e}")
            return False


    def mark_order_returned_from_no_product(self, order_id: int) -> bool:
        """Отмечает что заказ вернулся из no-product"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE processed_orders
                    SET returned_from_no_product = 1, updated_at = CURRENT_TIMESTAMP
                    WHERE order_id = ?
                """, (order_id,))
                conn.commit()
                logger.info(f"✅ Заказ {order_id} отмечен: вернулся из no-product")
                return True
        except Exception as e:
            logger.error(f"Ошибка при отметке возврата из no-product: {e}")
            return False


    def was_order_in_no_product(self, order_id: int) -> bool:
        """Проверяет был ли заказ когда-то в статусе no-product"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT was_in_no_product FROM processed_orders WHERE order_id = ?",
                    (order_id,)
                )
                result = cursor.fetchone()
                return result['was_in_no_product'] == 1 if result else False
        except Exception as e:
            logger.error(f"Ошибка при проверке no-product статуса: {e}")
            return False


    def is_order_returned_from_no_product(self, order_id: int) -> bool:
        """Проверяет вернулся ли заказ из no-product (один раз)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT returned_from_no_product FROM processed_orders WHERE order_id = ?",
                    (order_id,)
                )
                result = cursor.fetchone()
                return result['returned_from_no_product'] == 1 if result else False
        except Exception as e:
            logger.error(f"Ошибка при проверке возврата из no-product: {e}")
            return False


    def reset_order_for_renotification(self, order_id: int) -> bool:
        """
        Удаляет заказ из таблицы обработанных только если он вернулся из no-product
        Используется ТОЛЬКО для заказов которые были в no-product
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Проверяем что заказ был в no-product
                cursor.execute(
                    "SELECT was_in_no_product FROM processed_orders WHERE order_id = ?",
                    (order_id,)
                )
                result = cursor.fetchone()
                
                if not result or not result['was_in_no_product']:
                    logger.warning(f"⚠️ Заказ {order_id} не был в no-product, игнорируем")
                    return False
                
                # Удаляем только если это был возврат из no-product
                cursor.execute(
                    "DELETE FROM processed_orders WHERE order_id = ?",
                    (order_id,)
                )
                conn.commit()
                
                if cursor.rowcount > 0:
                    logger.info(f"✅ Заказ {order_id} удалён (возврат из no-product)")
                    return True
                else:
                    logger.warning(f"⚠️ Заказ {order_id} не найден")
                    return False
        except Exception as e:
            logger.error(f"❌ Ошибка при удалении заказа для переоправки: {e}")
            return False
    
    def mark_bouquet_ready_notified(self, order_id: int) -> bool:
        """
        Отмечает что уведомление о готовности букета было отправлено

        Args:
            order_id: ID заказа

        Returns:
            True если успешно, False если ошибка
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE processed_orders 
                    SET bouquet_ready_notified = 1, 
                        updated_at = CURRENT_TIMESTAMP
                    WHERE order_id = ?
                """, (order_id,))

                conn.commit()

                if cursor.rowcount > 0:
                    logger.info(f"✅ Заказ {order_id} отмечен как 'уведомление о готовности отправлено'")
                    return True
                else:
                    logger.warning(f"⚠️ Заказ {order_id} не найден в БД")
                    return False

        except Exception as e:
            logger.error(f"❌ Ошибка при отметке bouquet_ready_notified для заказа {order_id}: {e}")
            return False

    def is_bouquet_ready_notified(self, order_id: int) -> bool:
        """
        Проверяет было ли отправлено уведомление о готовности букета

        Args:
            order_id: ID заказа

        Returns:
            True если уведомление было отправлено, False если нет
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT bouquet_ready_notified FROM processed_orders WHERE order_id = ?",
                    (order_id,)
                )

                result = cursor.fetchone()
                return result['bouquet_ready_notified'] == 1 if result else False

        except Exception as e:
            logger.error(f"❌ Ошибка при проверке bouquet_ready_notified для заказа {order_id}: {e}")
            return False
