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


# ===========================================================================
# Спринт 2: редактирование и удаление операций, свои категории
# ===========================================================================

EXPENSE_CAFE = 3   # «Кафе» (расход)
INCOME_OTHER = 8   # «Прочее» (доход)


def read_file(data_path):
    """Содержимое data.json побайтово — чтобы сравнить «до» и «после»."""
    with open(data_path, "rb") as f:
        return f.read()


def op_body(type_="expense", amount="100", date="2026-11-24", category=EXPENSE_OTHER, comment=""):
    """Тело запроса для PUT /api/operations/<id>."""
    return {"type": type_, "amount": amount, "date": date, "categoryId": category, "comment": comment}


def balance(client):
    return client.get("/api/balance").get_json()["balance"]


def find_op(client, op_id):
    """Операция с данным id из GET /api/operations (или None)."""
    for op in client.get("/api/operations").get_json():
        if op["id"] == op_id:
            return op
    return None


def add_category(client, name, type_="expense", color="#123456"):
    return client.post("/api/categories", json={"name": name, "type": type_, "color": color})


# ---------- US-04: редактирование операции ----------

def test_edit_operation(client):
    """US-04: меняем сумму, дату, категорию и комментарий одной операции.

    Проверяем: ответ 200, новые значения сохранились, id прежний,
    баланс пересчитан, а вторая операция осталась точно такой же.
    """
    add(client, "income", "10000")                    # id 1
    add(client, "expense", "500", comment="обед")     # id 2
    other_before = find_op(client, 1)
    assert balance(client) == 1000000 - 50000

    r = client.put(
        "/api/operations/2",
        json=op_body(amount="2500,50", date="2026-11-20", category=EXPENSE_CAFE, comment="ужин"),
    )
    assert r.status_code == 200
    edited = r.get_json()
    assert edited["id"] == 2
    assert edited["amount"] == 250050
    assert edited["date"] == "2026-11-20"
    assert edited["categoryId"] == EXPENSE_CAFE
    assert edited["comment"] == "ужин"

    assert balance(client) == 1000000 - 250050
    assert find_op(client, 1) == other_before  # другая операция не изменилась


def test_edit_operation_change_type(client):
    """US-04: расход можно превратить в доход (с категорией дохода) —
    в балансе операция теперь идёт с плюсом."""
    add(client, "expense", "100")  # id 1, баланс −100 ₽
    r = client.put("/api/operations/1", json=op_body(type_="income", category=INCOME_OTHER))
    assert r.status_code == 200
    assert balance(client) == 10000


def test_edit_persists_after_restart(data_path):
    """US-04: изменения видны после «перезапуска» сервера."""
    client1 = create_app(data_path).test_client()
    add(client1, "expense", "100")
    client1.put("/api/operations/1", json=op_body(amount="777"))
    client2 = create_app(data_path).test_client()
    assert find_op(client2, 1)["amount"] == 77700


@pytest.mark.parametrize("bad", ["0", "-5", "абв", "1.555", "", None])
def test_edit_bad_amount_rejected(client, data_path, bad):
    """US-04: те же правила суммы, что в US-01. Ошибка → 400, файл не изменился."""
    add(client, "expense", "100")
    before = read_file(data_path)
    r = client.put("/api/operations/1", json=op_body(amount=bad))
    assert r.status_code == 400
    assert r.get_json()["error"]
    assert read_file(data_path) == before


def test_edit_wrong_category_type_rejected(client, data_path):
    """US-04: сменили тип на «доход», а категорию оставили от расхода → 400."""
    add(client, "expense", "100")
    before = read_file(data_path)
    r = client.put("/api/operations/1", json=op_body(type_="income", category=EXPENSE_OTHER))
    assert r.status_code == 400
    assert read_file(data_path) == before


def test_edit_missing_operation_404(client, data_path):
    """Редактирование несуществующей операции → 404, файл не изменился."""
    before = read_file(data_path)
    r = client.put("/api/operations/999", json=op_body())
    assert r.status_code == 404
    assert r.get_json()["error"]
    assert read_file(data_path) == before


# ---------- US-05: удаление операции ----------

def test_delete_operation(client):
    """US-05: операция исчезает из списка, баланс пересчитывается."""
    add(client, "income", "1000")  # id 1
    add(client, "expense", "300")  # id 2
    r = client.delete("/api/operations/2")
    assert r.status_code == 200
    ops = client.get("/api/operations").get_json()
    assert [op["id"] for op in ops] == [1]
    assert balance(client) == 100000


def test_delete_missing_operation_404(client, data_path):
    """US-05: удаление несуществующей операции → 404, файл не изменился."""
    add(client, "expense", "100")
    before = read_file(data_path)
    r = client.delete("/api/operations/999")
    assert r.status_code == 404
    assert r.get_json()["error"]
    assert read_file(data_path) == before


def test_bad_id_in_url_gives_json_404(client):
    """id не число (/api/operations/abc) → ошибка в виде JSON, а не HTML.
    Код 404 или 405 (405 — из-за того, что статика отдаётся из корня сайта)."""
    for r in (client.delete("/api/operations/abc"), client.put("/api/operations/abc", json={})):
        assert r.status_code in (404, 405)
        assert r.get_json()["error"]


# ---------- US-06: свои категории ----------

def test_create_category(client):
    """US-06: новая категория создаётся (201), пробелы по краям названия убираются,
    id = max + 1, и она появляется в GET /api/categories."""
    r = add_category(client, "  Подарки  ", color="#AABBCC")
    assert r.status_code == 201
    cat = r.get_json()
    assert cat == {"id": 9, "name": "Подарки", "type": "expense", "color": "#aabbcc"}
    assert cat in client.get("/api/categories").get_json()


def test_new_category_usable_for_operation(client):
    """US-06: в новую категорию сразу можно добавить операцию."""
    cat_id = add_category(client, "Подарки").get_json()["id"]
    assert add(client, "expense", "100", category=cat_id).status_code == 201


def test_duplicate_category_409(client, data_path):
    """US-06: «кафе» при существующей «Кафе» (тот же тип) → 409, файл не изменился."""
    before = read_file(data_path)
    r = add_category(client, "кафе")
    assert r.status_code == 409
    assert r.get_json()["error"] == "Такая категория уже есть"
    assert read_file(data_path) == before


def test_same_name_other_type_allowed(client):
    """Дубль считается только внутри одного типа: доход «Кафе» создать можно."""
    assert add_category(client, "Кафе", type_="income").status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "type": "expense", "color": "#123456"},          # пустое имя
        {"name": "   ", "type": "expense", "color": "#123456"},       # только пробелы
        {"name": "я" * 31, "type": "expense", "color": "#123456"},    # длиннее 30
        {"name": "Подарки", "type": "gift", "color": "#123456"},      # неизвестный тип
        {"name": "Подарки", "type": "expense", "color": "red"},       # не #rrggbb
        {"name": "Подарки", "type": "expense"},                       # нет цвета
    ],
)
def test_bad_category_rejected(client, data_path, body):
    """US-06: неправильные данные категории → 400, файл не изменился."""
    before = read_file(data_path)
    r = client.post("/api/categories", json=body)
    assert r.status_code == 400
    assert r.get_json()["error"]
    assert read_file(data_path) == before


def test_category_name_30_chars_ok(client):
    """Ровно 30 символов — ещё можно."""
    assert add_category(client, "я" * 30).status_code == 201


def test_rename_category(client):
    """US-06: переименование и смена цвета; тип не меняется.
    Операции ссылаются на категорию по id, поэтому новое имя «видят» сразу."""
    add(client, "expense", "100", category=EXPENSE_CAFE)
    r = client.put(f"/api/categories/{EXPENSE_CAFE}", json={"name": "Рестораны", "color": "#000000"})
    assert r.status_code == 200
    renamed = {"id": 3, "name": "Рестораны", "type": "expense", "color": "#000000"}
    assert r.get_json() == renamed
    assert renamed in client.get("/api/categories").get_json()
    assert find_op(client, 1)["categoryId"] == EXPENSE_CAFE


def test_rename_category_change_case_of_itself(client):
    """«Кафе» → «КАФЕ» — это не дубль: категория не сравнивается сама с собой."""
    r = client.put(f"/api/categories/{EXPENSE_CAFE}", json={"name": "КАФЕ", "color": "#9b59b6"})
    assert r.status_code == 200


def test_rename_category_to_duplicate_409(client, data_path):
    """US-06: переименовать «Кафе» в «продукты» нельзя — такая уже есть."""
    before = read_file(data_path)
    r = client.put(f"/api/categories/{EXPENSE_CAFE}", json={"name": "продукты", "color": "#9b59b6"})
    assert r.status_code == 409
    assert read_file(data_path) == before


def test_rename_other_forbidden_but_color_ok(client, data_path):
    """«Прочее» нельзя переименовать (409), но цвет сменить можно."""
    before = read_file(data_path)
    r = client.put(f"/api/categories/{EXPENSE_OTHER}", json={"name": "Разное", "color": "#7f8c8d"})
    assert r.status_code == 409
    assert read_file(data_path) == before

    r = client.put(f"/api/categories/{EXPENSE_OTHER}", json={"name": "Прочее", "color": "#000000"})
    assert r.status_code == 200
    assert r.get_json()["color"] == "#000000"


def test_rename_missing_category_404(client, data_path):
    """Переименование несуществующей категории → 404, файл не изменился."""
    before = read_file(data_path)
    r = client.put("/api/categories/999", json={"name": "X", "color": "#000000"})
    assert r.status_code == 404
    assert read_file(data_path) == before


def test_delete_empty_category(client):
    """US-06: категорию без операций можно удалить."""
    cat_id = add_category(client, "Подарки").get_json()["id"]
    r = client.delete(f"/api/categories/{cat_id}")
    assert r.status_code == 200
    ids = [c["id"] for c in client.get("/api/categories").get_json()]
    assert cat_id not in ids


def test_delete_category_with_operations_409(client, data_path):
    """US-06: категорию с операциями удалить нельзя → 409, файл не изменился."""
    add(client, "expense", "100", category=EXPENSE_CAFE)
    before = read_file(data_path)
    r = client.delete(f"/api/categories/{EXPENSE_CAFE}")
    assert r.status_code == 409
    assert r.get_json()["error"] == "В категории есть операции — удалить нельзя"
    assert read_file(data_path) == before


@pytest.mark.parametrize("cat_id", [EXPENSE_OTHER, INCOME_OTHER])
def test_delete_other_forbidden(client, data_path, cat_id):
    """US-06: «Прочее» (и расходов, и доходов) удалить нельзя никогда — даже пустую."""
    before = read_file(data_path)
    r = client.delete(f"/api/categories/{cat_id}")
    assert r.status_code == 409
    assert read_file(data_path) == before


def test_delete_missing_category_404(client, data_path):
    """Удаление несуществующей категории → 404, файл не изменился."""
    before = read_file(data_path)
    r = client.delete("/api/categories/999")
    assert r.status_code == 404
    assert read_file(data_path) == before
