// Логика страницы «Копилка». Все данные берём и отправляем только через API.

const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

// Такое же правило, как на сервере: цифры и до 2 знаков после точки/запятой.
const AMOUNT_RE = /^\d+([.,]\d{1,2})?$/;

let categories = []; // все категории с сервера

// ---------- Форматирование ----------

// 250050 -> «2 500,50 ₽». Считаем в целых копейках, без дробных чисел.
function formatMoney(kopecks) {
  const sign = kopecks < 0 ? "−" : "";
  const abs = Math.abs(kopecks);
  const rubles = Math.floor(abs / 100);
  const kop = String(abs % 100).padStart(2, "0");
  // Разделяем тысячи неразрывным пробелом
  const rublesText = String(rubles).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return sign + rublesText + "," + kop + " ₽";
}

// «2026-11-24» -> «24 ноября 2026»
function formatDay(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  return day + " " + MONTHS[month - 1] + " " + year;
}

// Сегодняшняя дата в формате YYYY-MM-DD (по местному времени)
function todayIso() {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return d.getFullYear() + "-" + mm + "-" + dd;
}

// ---------- Работа с сервером ----------

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || "Ошибка сервера");
    error.field = data.field;
    throw error;
  }
  return data;
}

async function loadBalance() {
  const data = await api("/api/balance");
  document.getElementById("balance").textContent = formatMoney(data.balance);
}

async function loadOperations() {
  const operations = await api("/api/operations");
  renderOperations(operations);
}

// ---------- Отрисовка списка ----------

function renderOperations(operations) {
  const list = document.getElementById("operations");
  const empty = document.getElementById("empty");
  list.innerHTML = "";

  if (operations.length === 0) {
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  // Операции уже отсортированы сервером, просто группируем подряд идущие дни
  let currentDate = null;
  let dayBlock = null;

  for (const op of operations) {
    if (op.date !== currentDate) {
      currentDate = op.date;
      dayBlock = document.createElement("div");
      dayBlock.className = "day";
      const title = document.createElement("div");
      title.className = "day-title";
      title.textContent = formatDay(op.date);
      dayBlock.appendChild(title);
      list.appendChild(dayBlock);
    }
    dayBlock.appendChild(renderOperation(op));
  }
}

function renderOperation(op) {
  const category = categories.find((c) => c.id === op.categoryId);

  const row = document.createElement("div");
  row.className = "op";

  const dot = document.createElement("span");
  dot.className = "dot";
  dot.style.background = category ? category.color : "#ccc";

  const name = document.createElement("span");
  name.className = "op-category";
  name.textContent = category ? category.name : "Без категории";

  // textContent (а не innerHTML) — чтобы комментарий не мог «сломать» страницу
  const comment = document.createElement("span");
  comment.className = "op-comment";
  comment.textContent = op.comment;

  const amount = document.createElement("span");
  amount.className = "op-amount " + op.type;
  const sign = op.type === "income" ? "+" : "−";
  amount.textContent = sign + formatMoney(op.amount);

  row.append(dot, name, comment, amount);
  return row;
}

// ---------- Форма ----------

function selectedType() {
  return document.querySelector('input[name="type"]:checked').value;
}

// Заполняет список категорий нужного типа, по умолчанию выбрано «Прочее»
function fillCategories() {
  const select = document.getElementById("category");
  const type = selectedType();
  select.innerHTML = "";
  for (const c of categories.filter((c) => c.type === type)) {
    const option = document.createElement("option");
    option.value = c.id;
    option.textContent = c.name;
    if (c.name === "Прочее") option.selected = true;
    select.appendChild(option);
  }
}

const FIELD_INPUTS = { amount: "amount", date: "date", categoryId: "category", comment: "comment" };

function showFieldError(field, message) {
  const inputId = FIELD_INPUTS[field];
  if (inputId) {
    document.getElementById(inputId).classList.add("invalid");
    document.getElementById(field + "-error").textContent = message;
  } else {
    document.getElementById("form-error").textContent = message;
  }
}

function clearErrors() {
  for (const field in FIELD_INPUTS) {
    document.getElementById(FIELD_INPUTS[field]).classList.remove("invalid");
    document.getElementById(field + "-error").textContent = "";
  }
  document.getElementById("form-error").textContent = "";
}

// Проверка на клиенте — для удобства. Главная проверка всё равно на сервере.
function checkAmount(text) {
  const value = text.trim().replace(/\s/g, "");
  if (value === "") return "Введите сумму";
  if (!AMOUNT_RE.test(value)) {
    return "Сумма должна быть положительным числом, не более 2 знаков после запятой";
  }
  if (/^[0.,]+$/.test(value)) return "Сумма должна быть больше нуля";
  return null;
}

async function onSubmit(event) {
  event.preventDefault();
  clearErrors();

  const amountText = document.getElementById("amount").value;
  const amountError = checkAmount(amountText);
  if (amountError) {
    showFieldError("amount", amountError);
    return;
  }

  const body = {
    type: selectedType(),
    amount: amountText,
    date: document.getElementById("date").value,
    categoryId: Number(document.getElementById("category").value),
    comment: document.getElementById("comment").value,
  };

  const button = event.target.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    await api("/api/operations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    // Успех: очищаем сумму и комментарий, обновляем список и баланс
    document.getElementById("amount").value = "";
    document.getElementById("comment").value = "";
    await Promise.all([loadOperations(), loadBalance()]);
    document.getElementById("amount").focus();
  } catch (error) {
    showFieldError(error.field, error.message);
  } finally {
    button.disabled = false;
  }
}

// ---------- Запуск ----------

async function init() {
  document.getElementById("date").value = todayIso();
  document.getElementById("op-form").addEventListener("submit", onSubmit);

  for (const radio of document.querySelectorAll('input[name="type"]')) {
    radio.addEventListener("change", () => {
      fillCategories();
      clearErrors();
    });
  }

  // Ошибка у поля пропадает, как только пользователь начинает его исправлять
  document.getElementById("amount").addEventListener("input", () => {
    document.getElementById("amount").classList.remove("invalid");
    document.getElementById("amount-error").textContent = "";
  });

  document.getElementById("add-first").addEventListener("click", () => {
    document.getElementById("amount").focus();
  });

  try {
    categories = await api("/api/categories");
    fillCategories();
    await Promise.all([loadOperations(), loadBalance()]);
  } catch (error) {
    const box = document.getElementById("load-error");
    box.textContent = "Не удалось загрузить данные: " + error.message;
    box.hidden = false;
  }
}

init();
