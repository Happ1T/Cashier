"""Тесты API «Копилки». Каждый тест работает со своим временным data.json.

Запуск: python -m pytest        (подробно: python -m pytest -v) 
pytest сам находит в папке tests/ файлы test_*.py и в них функции test_*,
запускает каждую по отдельности и сообщает, какие прошли, а какие нет.
Тест считается проваленным, если какой-нибудь assert внутри него оказался ложным.
"""

import os
import sys

import pytest

# Тесты лежат в tests/, а код сервера — в server/.
# Добавляем папку server/ в список мест, где Python ищет модули,
# чтобы сработала строка «from app import create_app».
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from app import create_app  # noqa: E402

# id категорий по умолчанию (см. storage.default_data)
EXPENSE_OTHER = 5  # «Прочее» (расход)
INCOME_SALARY = 6  # «Зарплата» (доход)


# ---------------------------------------------------------------------------
# Фикстуры — «заготовки», которые pytest готовит перед тестом.
# Если у функции-теста есть параметр с именем фикстуры (например, client),
# pytest сам вызовет фикстуру и передаст результат в тест.
# ---------------------------------------------------------------------------

@pytest.fixture
def data_path(tmp_path):
    """Путь к data.json во временной папке.

    tmp_path — встроенная фикстура pytest: для каждого теста создаётся новая
    пустая папка. Поэтому тесты не трогают настоящий server/data.json
    и не мешают друг другу — каждый начинает «с чистого листа».
    """
    return str(tmp_path / "data.json")


@pytest.fixture
def client(data_path):
    """Тестовый клиент Flask.

    Это «браузер понарошку»: он отправляет запросы прямо в приложение,
    без запуска настоящего сервера и без сети.
    client.get(url) / client.post(url, json=...) возвращают ответ,
    у которого есть status_code (200, 201, 400...) и get_json() — тело ответа.
    """
    app = create_app(data_path)
    app.testing = True  # в режиме тестов Flask показывает ошибки подробнее
    return app.test_client()


def add(client, type_, amount, date="2026-11-24", category=None, comment=""):
    """
    Если категория не указана — берём «Прочее» для расхода и «Зарплату» для дохода.
    """
    if category is None:
        category = EXPENSE_OTHER if type_ == "expense" else INCOME_SALARY
    return client.post(
        "/api/operations",
        json={
            "type": type_,
            "amount": amount,
            "date": date,
            "categoryId": category,
            "comment": comment,
        },
    )


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

def test_categories_by_default(client):
    """Новый файл данных содержит правильные категории по умолчанию:
    5 категорий расходов и 3 категории доходов, в нужном порядке."""
    cats = client.get("/api/categories").get_json()
    expense = [c["name"] for c in cats if c["type"] == "expense"]
    income = [c["name"] for c in cats if c["type"] == "income"]
    assert expense == ["Продукты", "Транспорт", "Кафе", "Развлечения", "Прочее"]
    assert income == ["Зарплата", "Стипендия", "Прочее"]


def test_empty_balance(client):
    """Когда операций нет: баланс равен 0, список операций пустой."""
    assert client.get("/api/balance").get_json() == {"balance": 0}
    assert client.get("/api/operations").get_json() == []


def test_create_expense_and_income_and_balance(client):
    """US-01, US-02, US-03: создаём доход 10 000 ₽ и расход 2 500,50 ₽.

    Проверяем:
    - сервер отвечает 201 (Created — «запись создана»);
    - сумма «2500,50» сохранилась как 250050 копеек;
    - accountId проставлен автоматически (= 1);
    - GET /api/operations возвращает обе операции;
    - баланс = 1 000 000 − 250 050 = 749 950 копеек.
    """
    r1 = add(client, "income", "10000", comment="Зарплата за ноябрь")
    r2 = add(client, "expense", "2500,50", comment="Продукты")
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r2.get_json()["amount"] == 250050
    assert r2.get_json()["accountId"] == 1

    ops = client.get("/api/operations").get_json()
    assert len(ops) == 2
    assert {op["type"] for op in ops} == {"income", "expense"}

    assert client.get("/api/balance").get_json() == {"balance": 749950}


# parametrize запускает ОДИН тест несколько раз с разными данными.
# Здесь тест выполнится 5 раз: для каждой пары (что ввёл пользователь, сколько копеек ждём).
@pytest.mark.parametrize(
    "text, kopecks",
    [("2500.50", 250050), ("2500,5", 250050), ("0,01", 1), ("7", 700), (" 12 ", 1200)],
)
def test_amount_formats(client, text, kopecks):
    """Правильные суммы в разных форматах принимаются и переводятся в копейки:
    точка и запятая, одна цифра после запятой («2500,5» = 2500,50),
    минимальная сумма 1 копейка, целое число, пробелы по краям."""
    r = add(client, "expense", text)
    assert r.status_code == 201
    assert r.get_json()["amount"] == kopecks


# Тест выполнится 8 раз — по разу для каждого неправильного значения.
@pytest.mark.parametrize("bad", ["0", "-5", "абв", "1.555", "", "0,00", "1e3", None])
def test_bad_amount_rejected(client, data_path, bad):
    """US-01: неправильная сумма отклоняется.

    Ноль, отрицательное число, буквы, 3 знака после запятой, пустая строка,
    «научная» запись 1e3 и отсутствие суммы → ответ 400 с текстом ошибки.

    Главное: файл data.json НЕ изменился. Для этого читаем файл
    побайтово ДО запроса и ПОСЛЕ и сравниваем — должно совпасть до байта.
    """
    with open(data_path, "rb") as f:
        before = f.read()
    r = add(client, "expense", bad)
    assert r.status_code == 400
    assert "error" in r.get_json()
    with open(data_path, "rb") as f:
        assert f.read() == before  # файл не изменился


# Тест выполнится 5 раз — для каждого неправильного запроса.
@pytest.mark.parametrize(
    "body",
    [
        # неизвестный тип операции
        {"type": "gift", "amount": "10", "date": "2026-11-24", "categoryId": 5},
        # дата не в формате ГГГГ-ММ-ДД
        {"type": "expense", "amount": "10", "date": "24.11.2026", "categoryId": 5},
        # формат верный, но такого дня не бывает
        {"type": "expense", "amount": "10", "date": "2026-02-30", "categoryId": 5},
        # категории с таким id нет
        {"type": "expense", "amount": "10", "date": "2026-11-24", "categoryId": 999},
        # категория дохода для расхода
        {"type": "expense", "amount": "10", "date": "2026-11-24", "categoryId": 6},
    ],
)
def test_other_validation(client, body):
    """Сервер проверяет не только сумму, но и остальные поля:
    на каждый неправильный запрос — ответ 400 и непустое сообщение об ошибке."""
    r = client.post("/api/operations", json=body)
    assert r.status_code == 400
    assert r.get_json()["error"]


def test_data_persists_after_restart(data_path):
    """US-01: данные сохраняются после перезапуска сервера.

    Создаём приложение, добавляем операцию. Потом создаём НОВОЕ приложение
    на том же файле (это то же самое, что остановить и снова запустить сервер)
    и проверяем, что операция на месте со всеми полями.
    """
    client1 = create_app(data_path).test_client()
    add(client1, "expense", "100", comment="кофе")

    # «Перезапуск сервера» — создаём приложение заново на том же файле
    client2 = create_app(data_path).test_client()
    ops = client2.get("/api/operations").get_json()
    assert len(ops) == 1
    assert ops[0]["comment"] == "кофе"
    assert ops[0]["amount"] == 10000


def test_sorting_by_date_then_id(client):
    """US-03: сортировка списка — новые даты сверху,
    при одинаковой дате — сначала добавленная позже (больший id).

    Добавляем операции вперемешку по датам и проверяем порядок id в ответе:
    24.11 (id 4), 24.11 (id 2), 22.11 (id 3), 20.11 (id 1).
    """
    add(client, "expense", "1", date="2026-11-20")  # id 1
    add(client, "expense", "2", date="2026-11-24")  # id 2
    add(client, "expense", "3", date="2026-11-22")  # id 3
    add(client, "expense", "4", date="2026-11-24")  # id 4
    ops = client.get("/api/operations").get_json()
    assert [op["id"] for op in ops] == [4, 2, 3, 1]


def test_ids_are_max_plus_one(client):
    """id новых операций выдаются по правилу max(id) + 1: 1, 2, 3..."""
    ids = [add(client, "expense", "1").get_json()["id"] for _ in range(3)]
    assert ids == [1, 2, 3]
