"""Чтение и запись файла data.json.
"""

import json
import os


def default_data():
    """Структура данных для нового (пустого) файла."""
    return {
        "accounts": [
            {"id": 1, "name": "Основной", "initial": 0},
        ],
        "categories": [
            # Категории расходов
            {"id": 1, "name": "Продукты", "type": "expense", "color": "#e67e22"},
            {"id": 2, "name": "Транспорт", "type": "expense", "color": "#3498db"},
            {"id": 3, "name": "Кафе", "type": "expense", "color": "#9b59b6"},
            {"id": 4, "name": "Развлечения", "type": "expense", "color": "#e84393"},
            {"id": 5, "name": "Прочее", "type": "expense", "color": "#7f8c8d"},
            # Категории доходов
            {"id": 6, "name": "Зарплата", "type": "income", "color": "#27ae60"},
            {"id": 7, "name": "Стипендия", "type": "income", "color": "#16a085"},
            {"id": 8, "name": "Прочее", "type": "income", "color": "#95a5a6"},
        ],
        "operations": [],
        "budgets": [],
        "recurring": [],
    }


def save_data(path, data):
    """Сохраняет данные в файл path через временный файл."""
    tmp_path = os.path.join(os.path.dirname(path), "data.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def load_data(path):
    """Читает данные из файла. Если файла нет — создаёт его с данными по умолчанию."""
    if not os.path.exists(path):
        data = default_data()
        save_data(path, data)
        return data
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def next_id(items):
    """Новый id = максимальный id в списке + 1 (или 1, если список пуст)."""
    if not items:
        return 1
    return max(item["id"] for item in items) + 1
