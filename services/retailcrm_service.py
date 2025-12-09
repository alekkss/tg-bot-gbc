import requests
from typing import Optional, Dict, List, Union
import logging
import json
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

logger = logging.getLogger(__name__)


class RetailCRMService:
    """Сервис для работы с RetailCRM API с автоматическим retry"""
    
    def __init__(self, api_key: str, domain: str):
        self.api_key = api_key
        self.domain = domain
        self.base_url = f"{domain}/api/v5"
        self._stores_cache = None
        self._products_cache = None  # Кэш товаров
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout)),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    def _make_get_request(self, url: str, params: dict, timeout: int = 10) -> requests.Response:
        """Выполняет GET запрос с автоматическим retry"""
        logger.debug(f"GET запрос: {url}")
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return response
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout)),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    def _make_post_request(self, url: str, params: dict, data: dict, timeout: int = 10) -> requests.Response:
        """Выполняет POST запрос с автоматическим retry"""
        logger.debug(f"POST запрос: {url}")
        response = requests.post(url, params=params, data=data, timeout=timeout)
        response.raise_for_status()
        return response
    
    def get_order_by_number(self, order_number: str) -> Optional[Dict]:
        """Получает информацию о заказе по его номеру"""
        url = f"{self.base_url}/orders"
        params = {
            "apiKey": self.api_key,
            "filter[numbers][]": order_number,
            "limit": 20
        }
        
        try:
            response = self._make_get_request(url, params)
            data = response.json()
            if data.get('orders'):
                return data['orders'][0]
            return None
        except requests.RequestException as e:
            logger.error(f"Ошибка получения заказа {order_number}: {e}")
            return None
    
    def get_order_by_id(self, order_id: int) -> Optional[Dict]:
        """Получает информацию о заказе по его ID"""
        url = f"{self.base_url}/orders/{order_id}"
        params = {
            "apiKey": self.api_key,
            "by": "id"
        }
        
        try:
            response = self._make_get_request(url, params)
            data = response.json()
            if data.get('order'):
                return data['order']
            return None
        except requests.RequestException as e:
            logger.error(f"Ошибка получения заказа по ID {order_id}: {e}")
            return None
    
    def get_all_statuses(self) -> Optional[Dict]:
        """Получает словарь всех статусов заказов из справочника"""
        url = f"{self.base_url}/reference/statuses"
        params = {
            "apiKey": self.api_key
        }
        
        try:
            response = self._make_get_request(url, params)
            data = response.json()
            if data.get('statuses'):
                return data['statuses']
            return None
        except requests.RequestException as e:
            logger.error(f"Ошибка получения статусов: {e}")
            return None
    
    def get_stores(self) -> Union[Dict, List]:
        """Получает данные о складах/магазинах с кэшированием"""
        if self._stores_cache:
            return self._stores_cache
        
        url = f"{self.base_url}/reference/stores"
        params = {
            "apiKey": self.api_key
        }
        
        try:
            response = self._make_get_request(url, params)
            data = response.json()
            if data.get('stores'):
                self._stores_cache = data['stores']
                return data['stores']
            return {}
        except requests.RequestException as e:
            logger.error(f"Ошибка получения складов: {e}")
            return {}
    
    def get_all_products(self) -> Dict[str, str]:
        """
        Получает ВСЕ товары и создаёт словарь {артикул: imageUrl}
        С кэшированием для быстрого доступа
        """
        if self._products_cache:
            return self._products_cache
        
        logger.info("Загрузка всех товаров из RetailCRM...")
        
        products_map = {}
        page = 1
        total_loaded = 0
        
        try:
            while True:
                url = f"{self.base_url}/store/products"
                params = {
                    "apiKey": self.api_key,
                    "limit": 100,  # Максимум за раз
                    "page": page
                }
                
                response = requests.get(url, params=params, timeout=30)
                
                if response.status_code != 200:
                    logger.error(f"Ошибка загрузки товаров (страница {page}): {response.status_code}")
                    break
                
                data = response.json()
                
                if not data.get('products'):
                    break  # Больше товаров нет
                
                # Добавляем товары в словарь
                for product in data['products']:
                    article = product.get('article')
                    image_url = product.get('imageUrl')
                    
                    if article and image_url:
                        products_map[article] = image_url
                        total_loaded += 1
                
                # Проверяем есть ли ещё страницы
                pagination = data.get('pagination', {})
                total_page_count = pagination.get('totalPageCount', 1)
                
                if page >= total_page_count:
                    break  # Загрузили все страницы
                
                page += 1
            
            logger.info(f"✅ Загружено товаров с фото: {total_loaded}")
            
            # Кэшируем результат
            self._products_cache = products_map
            return products_map
        
        except Exception as e:
            logger.error(f"Ошибка при загрузке товаров: {e}")
            return {}
    
    def get_product_image_by_article(self, article: str) -> Optional[str]:
        """Получает URL основного изображения товара по артикулу"""
        # Получаем все товары (из кэша или загружаем)
        products_map = self.get_all_products()
        
        # Ищем товар по артикулу
        if article in products_map:
            image_url = products_map[article]
            logger.info(f"✅ Найдено изображение для артикула {article}: {image_url}")
            return image_url
        else:
            logger.debug(f"⚠️ Товар с артикулом {article} не найден или нет фото")
            return None
    
    def get_product_images_from_order(self, order: Dict) -> List[str]:
        """Получает список URL изображений всех товаров из заказа"""
        image_urls = []
        
        if 'items' not in order or not order['items']:
            logger.info("В заказе нет товаров")
            return image_urls
        
        logger.info(f"Поиск изображений для {len(order['items'])} товаров")
        
        for idx, item in enumerate(order['items'], 1):
            offer = item.get('offer', {})
            article = offer.get('article')
            item_name = offer.get('displayName', 'N/A')
            
            if article:
                logger.info(f"Товар {idx}: {item_name} (артикул: {article})")
                image_url = self.get_product_image_by_article(article)
                
                if image_url:
                    image_urls.append(image_url)
                else:
                    logger.info(f"⚠️ Изображение для товара '{item_name}' не найдено")
            else:
                logger.info(f"⚠️ У товара '{item_name}' нет артикула")
        
        logger.info(f"Найдено изображений: {len(image_urls)} из {len(order['items'])} товаров")
        return image_urls
    
    def update_order_status(self, order_id: int, new_status: str) -> bool:
        """Обновляет статус заказа с retry механизмом"""
        # Сначала получаем информацию о заказе
        order = self.get_order_by_id(order_id)
        if not order:
            logger.error(f"Не удалось получить информацию о заказе {order_id}")
            return False
        
        site = order.get('site')
        if not site:
            logger.error(f"У заказа {order_id} не указан site")
            return False
        
        url = f"{self.base_url}/orders/{order_id}/edit"
        
        # Формируем данные для обновления - только статус
        order_data = {
            "status": new_status
        }
        
        # site передаём в параметрах URL
        params = {
            "apiKey": self.api_key,
            "by": "id",
            "site": site
        }
        
        # Отправляем как form data с JSON строкой
        data = {
            "order": json.dumps(order_data)
        }
        
        try:
            response = self._make_post_request(url, params, data)
            result = response.json()
            
            if result.get('success'):
                logger.info(f"Статус заказа {order_id} успешно обновлён на '{new_status}'")
                return True
            else:
                logger.error(f"Ошибка обновления статуса: {result}")
                return False
        except requests.RequestException as e:
            logger.error(f"Ошибка запроса обновления статуса заказа {order_id}: {e}")
            return False
    
    def get_orders_by_status(self, status_code: str) -> Optional[List[Dict]]:
        """Получает список заказов с определённым статусом"""
        url = f"{self.base_url}/orders"
        
        params = {
            "apiKey": self.api_key,
            "limit": 100,
            "page": 1
        }
        
        try:
            response = self._make_get_request(url, params)
            data = response.json()
            
            if data.get('orders'):
                all_orders = data['orders']
                
                # Фильтруем заказы по статусу на стороне Python
                filtered_orders = [
                    order for order in all_orders 
                    if order.get('status') == status_code
                ]
                
                return filtered_orders
            
            return []
        except requests.RequestException as e:
            logger.error(f"Ошибка получения заказов со статусом {status_code}: {e}")
            return []
