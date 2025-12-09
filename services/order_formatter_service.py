from typing import Dict


class OrderFormatterService:
    """Сервис для форматирования информации о заказе"""
    
    STATUS_TRANSLATION = {
        'send-to-assembling': 'Отправлен на сборку',
        'complete': 'Завершен',
        'cancel-other': 'Отменен',
        'prepayed': 'Предоплачен',
        'otzyv-reshen': 'Отзыв решен',
        'return': 'Возврат',
        'new': 'Новый',
        'assembling': 'Комплектуется',
        'ready': 'Готов к выдаче',
        'delivering': 'Доставляется',
        'courier': 'Курьерская доставка',
        'pickup': 'Самовывоз',
        'paid': 'Оплачен',
        'not-paid': 'Не оплачен',
        'in-reserve': 'В резерве'
    }
    
    @classmethod
    def translate_status(cls, status_code: str) -> str:
        """Переводит код статуса на русский"""
        return cls.STATUS_TRANSLATION.get(status_code, status_code)
    
    @classmethod
    def format_order_info(cls, order: Dict) -> str:
        """Форматирует информацию о заказе для отображения в Telegram"""
        lines = []
        
        lines.append("═" * 40)
        lines.append(f"📦 ЗАКАЗ №{order.get('number', 'N/A')}")
        lines.append("═" * 40)
        lines.append("")
        
        # Основная информация
        lines.append("📋 ОСНОВНЫЕ ДАННЫЕ:")
        # lines.append(f"ID: {order.get('id', 'N/A')}")
        lines.append(f"Статус: {cls.translate_status(order.get('status', 'N/A'))}")
        lines.append(f"Создан: {order.get('createdAt', 'N/A')}")
        lines.append(f"Сумма: {order.get('totalSumm', 0)} {order.get('currency', 'RUB')}")
        lines.append(f"Скидка: {order.get('discountManualAmount', 0)} {order.get('currency', 'RUB')}")
        lines.append("")
        
        # Клиент
        lines.append("👤 КЛИЕНТ:")
        lines.append(f"Имя: {order.get('firstName', 'N/A')} {order.get('lastName', 'N/A')}")
        lines.append(f"Телефон: {order.get('phone', 'N/A')}")
        
        customer = order.get('customer', {})
        if customer.get('email'):
            lines.append(f"Email: {customer['email']}")
        
        lines.append("")
        
        # Доставка
        if 'delivery' in order:
            delivery = order['delivery']
            lines.append("🚚 ДОСТАВКА:")
            lines.append(f"Тип: {cls.translate_status(delivery.get('code', 'N/A'))}")
            lines.append(f"Стоимость: {delivery.get('cost', 0)} руб.")
            lines.append(f"Дата: {delivery.get('date', 'N/A')}")
            
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
                    lines.append(f"Адрес: {', '.join(address_parts)}")
            lines.append("")
        
        # Оплата
        if 'payments' in order and order['payments']:
            lines.append("💳 ОПЛАТА:")
            payments = order['payments']
            
            if isinstance(payments, dict):
                for payment_id, payment in payments.items():
                    lines.append(f"Тип: {payment.get('type', 'N/A')}")
                    lines.append(f"Статус: {cls.translate_status(payment.get('status', 'N/A'))}")
                    lines.append(f"Сумма: {payment.get('amount', 0)} руб.")
            elif isinstance(payments, list):
                for payment in payments:
                    if isinstance(payment, dict):
                        lines.append(f"Тип: {payment.get('type', 'N/A')}")
                        lines.append(f"Статус: {cls.translate_status(payment.get('status', 'N/A'))}")
                        lines.append(f"Сумма: {payment.get('amount', 0)} руб.")
            lines.append("")
        
        # Товары
        if 'items' in order:
            lines.append("🛍 ТОВАРЫ:")
            for idx, item in enumerate(order['items'], 1):
                offer = item.get('offer', {})
                item_name = offer.get('displayName', offer.get('name', 'N/A'))
                quantity = item.get('quantity', 0)
                price = item.get('prices', [{}])[0].get('price', 0)
                
                lines.append(f"{idx}. {item_name}")
                lines.append(f"   Кол-во: {quantity}, Цена: {price} руб.")
            lines.append("")
        
        # Комментарии
        if order.get('customerComment'):
            lines.append("💬 КОММЕНТАРИЙ КЛИЕНТА:")
            lines.append(order['customerComment'])
            lines.append("")
        
        if order.get('managerComment'):
            lines.append("📝 КОММЕНТАРИЙ МЕНЕДЖЕРА:")
            lines.append(order['managerComment'])
            lines.append("")
        
        lines.append("═" * 40)
        
        return '\n'.join(lines)
