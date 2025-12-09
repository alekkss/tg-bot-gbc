import redis
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Rate Limiter на основе Redis
    
    Использует алгоритм Fixed Window Counter:
    - Считает количество запросов в окне времени
    - Если превышен лимит - блокирует
    
    Примеры использования:
    - Защита от спама кнопок
    - Ограничение частоты запросов к API
    - Защита от DDoS
    """
    
    def __init__(
        self, 
        host: str = 'localhost', 
        port: int = 6379, 
        db: int = 0,
        prefix: str = 'rate_limit'
    ):
        """
        Args:
            host: Redis хост
            port: Redis порт
            db: Номер БД Redis (0-15)
            prefix: Префикс ключей (для изоляции)
        """
        try:
            self.redis = redis.Redis(
                host=host,
                port=port,
                db=db,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            # Проверяем подключение
            self.redis.ping()
            self.prefix = prefix
            logger.info(f"✅ Redis Rate Limiter подключён: {host}:{port}/{db}")
        except redis.ConnectionError as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            logger.warning("⚠️ Rate Limiter работает в FALLBACK режиме (без ограничений)")
            self.redis = None
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации Redis: {e}")
            self.redis = None
    
    def _get_key(self, identifier: str, action: str) -> str:
        """Генерирует ключ Redis"""
        return f"{self.prefix}:{action}:{identifier}"
    
    async def check_rate_limit(
        self,
        identifier: str,
        action: str,
        limit: int = 10,
        window: int = 60
    ) -> tuple[bool, int]:
        """
        Проверяет rate limit для действия
        
        Args:
            identifier: Идентификатор (user_id, IP, etc)
            action: Действие ('confirm_order', 'click_button', etc)
            limit: Максимальное количество запросов
            window: Окно времени в секундах
        
        Returns:
            Tuple[bool, int]: (is_limited, remaining_requests)
            - is_limited: True если лимит превышен
            - remaining_requests: Сколько осталось запросов
        
        Примеры:
            >>> is_limited, remaining = await check_rate_limit(
            ...     identifier='12345',
            ...     action='confirm_order',
            ...     limit=5,
            ...     window=60
            ... )
            >>> if is_limited:
            ...     print(f"Превышен лимит! Осталось: {remaining}")
        """
        # Fallback если Redis недоступен
        if self.redis is None:
            logger.warning("⚠️ Redis недоступен, rate limiting отключен")
            return False, limit
        
        try:
            key = self._get_key(identifier, action)
            
            # Увеличиваем счётчик
            current = self.redis.incr(key)
            
            # Если первый запрос - устанавливаем TTL
            if current == 1:
                self.redis.expire(key, window)
            
            # Вычисляем оставшиеся запросы
            remaining = max(0, limit - current)
            
            # Проверяем лимит
            is_limited = current > limit
            
            if is_limited:
                ttl = self.redis.ttl(key)
                logger.warning(
                    f"⚠️ Rate limit превышен: {action} для {identifier} "
                    f"({current}/{limit}), осталось {ttl}s до сброса"
                )
            
            return is_limited, remaining
            
        except redis.RedisError as e:
            logger.error(f"❌ Redis ошибка в check_rate_limit: {e}")
            # Fallback - разрешаем запрос при ошибке
            return False, limit
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка в check_rate_limit: {e}")
            return False, limit
    
    def get_remaining_time(self, identifier: str, action: str) -> Optional[int]:
        """
        Получить время до сброса лимита (в секундах)
        
        Returns:
            int: Секунд до сброса или None если нет активного лимита
        """
        if self.redis is None:
            return None
        
        try:
            key = self._get_key(identifier, action)
            ttl = self.redis.ttl(key)
            return ttl if ttl > 0 else None
        except Exception as e:
            logger.error(f"❌ Ошибка get_remaining_time: {e}")
            return None
    
    def reset_limit(self, identifier: str, action: str) -> bool:
        """
        Сбросить лимит для пользователя (admin функция)
        
        Returns:
            bool: True если успешно сброшено
        """
        if self.redis is None:
            return False
        
        try:
            key = self._get_key(identifier, action)
            deleted = self.redis.delete(key)
            logger.info(f"🔄 Лимит сброшен для {identifier}:{action}")
            return deleted > 0
        except Exception as e:
            logger.error(f"❌ Ошибка reset_limit: {e}")
            return False
    
    def get_stats(self) -> dict:
        """Получить статистику использования"""
        if self.redis is None:
            return {'status': 'unavailable'}
        
        try:
            # Получаем все ключи rate limit
            pattern = f"{self.prefix}:*"
            keys = self.redis.keys(pattern)
            
            stats = {
                'status': 'active',
                'total_limits': len(keys),
                'active_limits': [],
            }
            
            for key in keys[:10]:  # Показываем первые 10
                value = self.redis.get(key)
                ttl = self.redis.ttl(key)
                stats['active_limits'].append({
                    'key': key,
                    'count': value,
                    'expires_in': ttl
                })
            
            return stats
        except Exception as e:
            logger.error(f"❌ Ошибка get_stats: {e}")
            return {'status': 'error', 'error': str(e)}


# Глобальный экземпляр (singleton)
rate_limiter = None


def get_rate_limiter(
    host: str = 'localhost',
    port: int = 6379,
    db: int = 0
) -> RateLimiter:
    """
    Получить глобальный экземпляр RateLimiter (singleton pattern)
    
    Args:
        host: Redis хост
        port: Redis порт
        db: Номер БД
    
    Returns:
        RateLimiter instance
    """
    global rate_limiter
    
    if rate_limiter is None:
        rate_limiter = RateLimiter(host=host, port=port, db=db)
    
    return rate_limiter
