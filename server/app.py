"""Flask-приложение «Копилка»: отдаёт страницу и API для операций."""

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


class ValidationError(Exception):
    """Ошибка в данных от пользователя. field — какое поле подсветить."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.message = message
        self.field = field


def parse_amount(value):
    """Переводит «2500,50» или «2500.50» в копейки (250050). Без float!"""
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
    """Проверяет данные новой операции и возвращает готовый словарь."""
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


def create_app(data_path=DEFAULT_DATA_PATH):
    """Создаёт приложение. data_path можно подменить в тестах."""
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
    app.json.ensure_ascii = False  # русские буквы в ответах API без с...
    lock = threading.Lock()  # чтобы два запроса не записывали файл одновременно

    storage.load_data(data_path)  # создаём data.json, если его ещё нет

    @app.errorhandler(ValidationError)
    def handle_validation_error(err):
        body = {"error": err.message}
        if err.field:
            body["field"] = err.field
        return jsonify(body), 400

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
