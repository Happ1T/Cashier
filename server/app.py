"""Flask-приложение «Копилка»: отдаёт страницу и API для операций и категорий."""

import os
import re
import threading
from datetime import date as date_cls

from flask import Flask, jsonify, request

import storage

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(SERVER_DIR, "..", "static")
DEFAULT_DATA_PATH = os.path.join(SERVER_DIR, "data.json")

# Сумма: цифры, затем по желанию точка или запятая и 1–2 цифры.
AMOUNT_RE = re.compile(r"^\d+([.,]\d{1,2})?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_AMOUNT = 100_000_000_00  # 100 млн рублей в копейках — защита от опечаток
MAX_COMMENT = 200
MAX_CATEGORY_NAME = 30
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
OTHER_NAME = "Прочее"  # категорию «Прочее» нельзя удалить и переименовать


class ValidationError(Exception):
    """Ошибка в данных от пользователя. field — какое поле подсветить.

    status — HTTP-код ответа: 400 «неправильные данные».
    """

    status = 400

    def __init__(self, message, field=None):
        super().__init__(message)
        self.message = message
        self.field = field


class NotFoundError(ValidationError):
    """Запись с таким id не найдена."""

    status = 404


class ConflictError(ValidationError):
    """Данные правильные, но действие невозможно (дубль, категория занята)."""

    status = 409


def find_by_id(items, item_id, message):
    """Ищет запись по id в списке. Нет такой — ошибка 404."""
    for item in items:
        if item["id"] == item_id:
            return item
    raise NotFoundError(message)


def parse_amount(value):
    """Ввод и перевод в копейки"""
    if isinstance(value, bool) or value is None:
        raise ValidationError("Введите сумму", "amount")
    text = str(value).strip().replace(" ", "")
    if text == "":
        raise ValidationError("Введите сумму", "amount")
    if not AMOUNT_RE.match(text):
        raise ValidationError(
            "Сумма должна быть положительным числом, не более 2 знаков после запятой",
            "amount",
        )
    text = text.replace(",", ".")
    if "." in text:
        rubles, kopecks = text.split(".")
        kopecks = kopecks.ljust(2, "0")  # «5» -> «50»
    else:
        rubles, kopecks = text, "00"
    amount = int(rubles) * 100 + int(kopecks)
    if amount <= 0:
        raise ValidationError("Сумма должна быть больше нуля", "amount")
    if amount > MAX_AMOUNT:
        raise ValidationError("Слишком большая сумма", "amount")
    return amount


def parse_date(value):
    """Проверяет дату в формате YYYY-MM-DD."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ValidationError("Дата должна быть в формате ГГГГ-ММ-ДД", "date")
    try:
        date_cls.fromisoformat(value)
    except ValueError:
        raise ValidationError("Такой даты не существует", "date")
    return value


def validate_operation(body, data):
    """Проверяет данные операции (новой или изменённой) и возвращает словарь полей."""
    if not isinstance(body, dict):
        raise ValidationError("Ожидались данные в формате JSON")

    op_type = body.get("type")
    if op_type not in ("expense", "income"):
        raise ValidationError("Тип операции должен быть «расход» или «доход»", "type")

    amount = parse_amount(body.get("amount"))
    op_date = parse_date(body.get("date"))

    category_id = body.get("categoryId")
    category = None
    if isinstance(category_id, bool):  # в Python True == 1, отсекаем
        category_id = None
    for c in data["categories"]:
        if c["id"] == category_id:
            category = c
    if category is None:
        raise ValidationError("Выберите категорию", "categoryId")
    if category["type"] != op_type:
        raise ValidationError("Категория не подходит к типу операции", "categoryId")

    comment = body.get("comment", "")
    if comment is None:
        comment = ""
    if not isinstance(comment, str):
        raise ValidationError("Комментарий должен быть строкой", "comment")
    comment = comment.strip()
    if len(comment) > MAX_COMMENT:
        raise ValidationError(f"Комментарий не длиннее {MAX_COMMENT} символов", "comment")

    return {
        "type": op_type,
        "amount": amount,
        "date": op_date,
        "categoryId": category_id,
        "accountId": 1,
        "comment": comment,
    }


def validate_category(body, data, current=None):
    """Проверяет данные категории и возвращает {name, type, color}.

    current — категория, которую редактируем (None — создаём новую).
    Тип задаётся только при создании: у старых операций категория должна
    оставаться того же типа, что и операция.
    """
    if not isinstance(body, dict):
        raise ValidationError("Ожидались данные в формате JSON")

    if current is None:
        cat_type = body.get("type")
        if cat_type not in ("expense", "income"):
            raise ValidationError("Тип категории должен быть «расход» или «доход»", "type")
    else:
        cat_type = current["type"]

    name = body.get("name")
    if not isinstance(name, str) or name.strip() == "":
        raise ValidationError("Введите название", "name")
    name = name.strip()
    if len(name) > MAX_CATEGORY_NAME:
        raise ValidationError(
            f"Название не длиннее {MAX_CATEGORY_NAME} символов", "name"
        )

    color = body.get("color")
    if not isinstance(color, str) or not COLOR_RE.match(color):
        raise ValidationError("Цвет должен быть в формате #rrggbb", "color")
    color = color.lower()

    if current is not None and current["name"] == OTHER_NAME and name != OTHER_NAME:
        raise ConflictError("Категорию «Прочее» нельзя переименовать", "name")

    # Дубль: то же имя у другой категории того же типа, без учёта регистра.
    # casefold() — «правильный» lower() для любых языков.
    for c in data["categories"]:
        if c is current or c["type"] != cat_type:
            continue
        if c["name"].casefold() == name.casefold():
            raise ConflictError("Такая категория уже есть", "name")

    return {"name": name, "type": cat_type, "color": color}


def create_app(data_path=DEFAULT_DATA_PATH):
    """Создаёт приложение"""
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
    app.json.ensure_ascii = False  # русские буквы в ответах API без с...
    lock = threading.Lock()  # чтобы два запроса не записывали файл одновременно

    storage.load_data(data_path)  # создаём data.json, если его ещё нет

    @app.errorhandler(ValidationError)
    def handle_validation_error(err):
        body = {"error": err.message}
        if err.field:
            body["field"] = err.field
        return jsonify(body), err.status

    @app.errorhandler(404)
    @app.errorhandler(405)
    def handle_bad_url(err):
        # Неизвестный адрес API (например, DELETE /api/operations/abc) — отвечаем
        # JSON, а не HTML-страницей, чтобы интерфейс мог показать ошибку.
        # 405 бывает потому, что статика отдаётся из корня сайта (GET /<путь>),
        # и Flask считает, что адрес есть, но только для GET.
        if request.path.startswith("/api/"):
            return jsonify({"error": "Такого адреса API нет"}), err.code
        return err

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/categories")
    def get_categories():
        data = storage.load_data(data_path)
        return jsonify(data["categories"])

    @app.get("/api/operations")
    def get_operations():
        data = storage.load_data(data_path)
        # Новые сверху: сначала по дате, при равной дате — по id.
        ops = sorted(
            data["operations"], key=lambda op: (op["date"], op["id"]), reverse=True
        )
        return jsonify(ops)

    @app.post("/api/operations")
    def create_operation():
        body = request.get_json(silent=True)
        with lock:
            data = storage.load_data(data_path)
            operation = validate_operation(body, data)
            operation = {"id": storage.next_id(data["operations"]), **operation}
            data["operations"].append(operation)
            storage.save_data(data_path, data)
        return jsonify(operation), 201

    @app.put("/api/operations/<int:op_id>")
    def update_operation(op_id):
        body = request.get_json(silent=True)
        with lock:
            data = storage.load_data(data_path)
            operation = find_by_id(data["operations"], op_id, "Операция не найдена")
            new_fields = validate_operation(body, data)
            operation.update(new_fields)  # id остаётся прежним
            storage.save_data(data_path, data)
        return jsonify(operation)

    @app.delete("/api/operations/<int:op_id>")
    def delete_operation(op_id):
        with lock:
            data = storage.load_data(data_path)
            operation = find_by_id(data["operations"], op_id, "Операция не найдена")
            data["operations"].remove(operation)
            storage.save_data(data_path, data)
        return jsonify({"ok": True})

    @app.post("/api/categories")
    def create_category():
        body = request.get_json(silent=True)
        with lock:
            data = storage.load_data(data_path)
            category = validate_category(body, data)
            category = {"id": storage.next_id(data["categories"]), **category}
            data["categories"].append(category)
            storage.save_data(data_path, data)
        return jsonify(category), 201

    @app.put("/api/categories/<int:cat_id>")
    def update_category(cat_id):
        body = request.get_json(silent=True)
        with lock:
            data = storage.load_data(data_path)
            category = find_by_id(data["categories"], cat_id, "Категория не найдена")
            new_fields = validate_category(body, data, current=category)
            category["name"] = new_fields["name"]
            category["color"] = new_fields["color"]
            storage.save_data(data_path, data)
        return jsonify(category)

    @app.delete("/api/categories/<int:cat_id>")
    def delete_category(cat_id):
        with lock:
            data = storage.load_data(data_path)
            category = find_by_id(data["categories"], cat_id, "Категория не найдена")
            if category["name"] == OTHER_NAME:
                raise ConflictError("Категорию «Прочее» удалить нельзя")
            for op in data["operations"]:
                if op["categoryId"] == cat_id:
                    raise ConflictError("В категории есть операции — удалить нельзя")
            data["categories"].remove(category)
            storage.save_data(data_path, data)
        return jsonify({"ok": True})

    @app.get("/api/balance")
    def get_balance():
        data = storage.load_data(data_path)
        balance = 0
        for op in data["operations"]:
            if op["type"] == "income":
                balance += op["amount"]
            else:
                balance -= op["amount"]
        return jsonify({"balance": balance})

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
