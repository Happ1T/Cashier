# Копилка

Веб-приложение для учёта личных финансов (учебный проект по Scrum).
Сервер — Python + Flask, данные хранятся в файле `server/data.json`.

## Установка (один раз)

Нужен Python 3.10 или новее.

**Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> Если PowerShell пишет, что запуск скриптов запрещён, выполните один раз:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## Запуск

Сначала активируйте окружение (`venv\Scripts\activate` или `source venv/bin/activate`), затем:

```
python server/app.py
```

Откройте в браузере: http://127.0.0.1:5000
Остановить сервер — `Ctrl+C`.

Файл `server/data.json` создаётся автоматически при первом запуске.
Чтобы начать «с чистого листа», остановите сервер и удалите этот файл.

## Тесты

```
python -m pytest
```

## Структура

```
server/app.py       — Flask-приложение и API
server/storage.py   — чтение/запись data.json
static/             — страница (index.html, style.css, app.js)
tests/test_api.py   — тесты API
```

## API

| Метод | Адрес | Что делает |
|---|---|---|
| GET  | /api/categories | список категорий |
| GET  | /api/operations | список операций (новые сверху) |
| POST | /api/operations | создать операцию |
| GET  | /api/balance    | `{"balance": <копейки>}` |

Пример тела POST:
```json
{"type": "expense", "amount": "2500,50", "date": "2026-11-24", "categoryId": 5, "comment": "Продукты"}
```
При ошибке сервер отвечает кодом 400 и `{"error": "сообщение"}`.
