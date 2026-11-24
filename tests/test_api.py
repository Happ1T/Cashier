"""Тесты API «Копилки». Каждый тест работает со своим временным data.json."""

import os
import sys

import pytest

# Чтобы можно было сделать «import app» из папки server/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from app import create_app  # noqa: E402

EXPENSE_OTHER = 5  # «Прочее» (расход)
INCOME_SALARY = 6  # «Зарплата» (доход)


@pytest.fixture
def data_path(tmp_path):
    return str(tmp_path / "data.json")


@pytest.fixture
def client(data_path):
    app = create_app(data_path)
    app.testing = True
    return app.test_client()


def add(client, type_, amount, date="2026-11-24", category=None, comment=""):
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


def test_categories_by_default(client):
    cats = client.get("/api/categories").get_json()
    expense = [c["name"] for c in cats if c["type"] == "expense"]
    income = [c["name"] for c in cats if c["type"] == "income"]
    assert expense == ["Продукты", "Транспорт", "Кафе", "Развлечения", "Прочее"]
    assert income == ["Зарплата", "Стипендия", "Прочее"]


def test_empty_balance(client):
    assert client.get("/api/balance").get_json() == {"balance": 0}
    assert client.get("/api/operations").get_json() == []


def test_create_expense_and_income_and_balance(client):
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


@pytest.mark.parametrize(
    "text, kopecks",
    [("2500.50", 250050), ("2500,5", 250050), ("0,01", 1), ("7", 700), (" 12 ", 1200)],
)
def test_amount_formats(client, text, kopecks):
    r = add(client, "expense", text)
    assert r.status_code == 201
    assert r.get_json()["amount"] == kopecks


@pytest.mark.parametrize("bad", ["0", "-5", "абв", "1.555", "", "0,00", "1e3", None])
def test_bad_amount_rejected(client, data_path, bad):
    with open(data_path, "rb") as f:
        before = f.read()
    r = add(client, "expense", bad)
    assert r.status_code == 400
    assert "error" in r.get_json()
    with open(data_path, "rb") as f:
        assert f.read() == before  # файл не изменился


@pytest.mark.parametrize(
    "body",
    [
        {"type": "gift", "amount": "10", "date": "2026-11-24", "categoryId": 5},
        {"type": "expense", "amount": "10", "date": "24.11.2026", "categoryId": 5},
        {"type": "expense", "amount": "10", "date": "2026-02-30", "categoryId": 5},
        {"type": "expense", "amount": "10", "date": "2026-11-24", "categoryId": 999},
        # категория дохода для расхода
        {"type": "expense", "amount": "10", "date": "2026-11-24", "categoryId": 6},
    ],
)
def test_other_validation(client, body):
    r = client.post("/api/operations", json=body)
    assert r.status_code == 400
    assert r.get_json()["error"]


def test_data_persists_after_restart(data_path):
    client1 = create_app(data_path).test_client()
    add(client1, "expense", "100", comment="кофе")

    # «Перезапуск сервера» — создаём приложение заново на том же файле
    client2 = create_app(data_path).test_client()
    ops = client2.get("/api/operations").get_json()
    assert len(ops) == 1
    assert ops[0]["comment"] == "кофе"
    assert ops[0]["amount"] == 10000


def test_sorting_by_date_then_id(client):
    add(client, "expense", "1", date="2026-11-20")  # id 1
    add(client, "expense", "2", date="2026-11-24")  # id 2
    add(client, "expense", "3", date="2026-11-22")  # id 3
    add(client, "expense", "4", date="2026-11-24")  # id 4
    ops = client.get("/api/operations").get_json()
    assert [op["id"] for op in ops] == [4, 2, 3, 1]


def test_ids_are_max_plus_one(client):
    ids = [add(client, "expense", "1").get_json()["id"] for _ in range(3)]
    assert ids == [1, 2, 3]
