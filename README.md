# Копилка

Веб-приложение для учёта личных финансов (учебный проект по Scrum).
Сервер — Python + Flask, данные хранятся в файле `server/data.json`.

## Установка (один раз)

Нужен Python 3.10 или новее.

**Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r readable/requirements.txt
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r readable/requirements.txt
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
| PUT  | /api/operations/&lt;id&gt; | изменить операцию |
| DELETE | /api/operations/&lt;id&gt; | удалить операцию |
| GET  | /api/balance    | `{"balance": <копейки>}` |
| POST | /api/categories | создать категорию (`name`, `type`, `color`) |
| PUT  | /api/categories/&lt;id&gt; | переименовать / сменить цвет (`name`, `color`) |
| DELETE | /api/categories/&lt;id&gt; | удалить категорию без операций |

Суммы передаются строкой («2500,50»), хранятся в целых копейках.

При ошибке сервер отвечает `{"error": "сообщение"}` и кодом:

| Код | Когда |
|---|---|
| 400 | неверные данные (сумма, дата, название, цвет…) |
| 404 | записи с таким id нет |
| 409 | конфликт: такая категория уже есть, в категории есть операции, попытка удалить или переименовать «Прочее» |
