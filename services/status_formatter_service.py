from typing import Dict


class StatusFormatterService:
    """Сервис для форматирования информации о статусах"""
    
    @staticmethod
    def format_statuses_list(statuses: Dict) -> str:
        """Форматирует словарь статусов для отображения в Telegram"""
        if not statuses or not isinstance(statuses, dict):
            return "❌ Статусы не найдены"
        
        lines = []
        lines.append("═" * 40)
        lines.append("📋 СПИСОК ВСЕХ СТАТУСОВ")
        lines.append("═" * 40)
        lines.append("")
        
        # Группируем статусы по группам
        status_groups = {}
        for status_code, status_data in statuses.items():
            if isinstance(status_data, dict):
                group_name = status_data.get('group', 'Без группы')
                if group_name not in status_groups:
                    status_groups[group_name] = []
                status_groups[group_name].append({
                    'code': status_code,
                    **status_data
                })
        
        # Выводим статусы по группам
        for group_name, group_statuses in status_groups.items():
            lines.append(f"📂 {group_name}:")
            lines.append("")
            
            for status in group_statuses:
                name = status.get('name', 'N/A')
                code = status.get('code', 'N/A')
                active = "✅" if status.get('active', False) else "❌"
                
                lines.append(f"{active} {name}")
                lines.append(f"   Код: {code}")
                
                # Добавляем цвет если есть
                if status.get('color'):
                    lines.append(f"   Цвет: {status['color']}")
                
                lines.append("")
        
        lines.append("═" * 40)
        lines.append(f"Всего статусов: {len(statuses)}")
        
        return '\n'.join(lines)
