// Логика страницы «Копилка». Все данные берём и отправляем только через API.

const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

// Такое же правило, как на сервере: цифры и до 2 знаков после точки/запятой.
const AMOUNT_RE = /^\d+([.,]\d{1,2})?$/;
const OTHER_NAME = "Прочее";
const DEFAULT_CAT_COLOR = "#1a73e8";

let categories = [];    // все категории с сервера
let operations = [];    // последний загруженный список операций
let editingId = null;   // id операции, открытой в форме (null — режим добавления)
let editingCatId = null; // id категории, открытой в форме категорий

// ---------- Форматирование ----------

// 250050 -> «2 500,50 ₽». Считаем в целых копейках, без дробных чисел.
//   — неразрывный пробел: сумма не разорвётся на две строки.
function formatMoney(kopecks) {
  const sign = kopecks < 0 ? "−" : "";
  const abs = Math.abs(kopecks);
  const rubles = Math.floor(abs / 100);
  const kop = String(abs % 100).padStart(2, "0");
  const rublesText = String(rubles).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return sign + rublesText + "," + kop + " ₽";
}

// Сумма операции со знаком: «−2 500,50 ₽» для расхода, «+…» для дохода
function signedMoney(op) {
  const sign = op.type === "income" ? "+" : "−";
  return sign + formatMoney(op.amount);
}

// 250050 -> «2500,50» — так сумма подставляется в поле формы при редактировании
function amountForInput(kopecks) {
  const rubles = Math.floor(kopecks / 100);
  const kop = kopecks % 100;
  if (kop === 0) return String(rubles);
  return rubles + "," + String(kop).padStart(2, "0");
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

// Запрос с телом в формате JSON (POST / PUT)
function sendJson(url, method, body) {
  return api(url, {
    method: method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function loadBalance() {
  const data = await api("/api/balance");
  document.getElementById("balance").textContent = formatMoney(data.balance);
}

async function loadOperations() {
  operations = await api("/api/operations");
  renderOperations();
}

// После изменения операций обновляем и список, и баланс
function reloadAll() {
  return Promise.all([loadOperations(), loadBalance()]);
}

// Ошибка над списком операций (например, не удалось удалить)
function showListError(message) {
  const box = document.getElementById("list-error");
  box.textContent = message;
  box.hidden = !message;
}

// ---------- Окно подтверждения ----------

// Показывает окно с текстом. Возвращает Promise: true — «Удалить», false — «Отмена»/Esc.
function askConfirm(text) {
  const dialog = document.getElementById("confirm-dialog");
  document.getElementById("confirm-text").textContent = text;
  dialog.returnValue = ""; // сбрасываем ответ с прошлого раза
  dialog.showModal();
  return new Promise((resolve) => {
    // Событие close приходит при любом закрытии: кнопкой или клавишей Esc
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
  });
}

// ---------- Список операций ----------

function renderOperations() {
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
  if (op.id === editingId) row.classList.add("selected");
  row.title = "Нажмите, чтобы изменить";
  row.addEventListener("click", () => startEdit(op));

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
  amount.textContent = signedMoney(op);

  // Корзина видна только при наведении на строку (см. style.css)
  const del = document.createElement("button");
  del.type = "button";
  del.className = "op-delete";
  del.textContent = "🗑";
  del.title = "Удалить";
  del.addEventListener("click", (event) => {
    event.stopPropagation(); // иначе клик «дойдёт» до строки и откроет редактирование
    deleteOperation(op);
  });

  row.append(dot, name, comment, amount, del);
  return row;
}

async function deleteOperation(op) {
  const ok = await askConfirm(
    "Удалить операцию: " + signedMoney(op) + ", " + formatDay(op.date) + "?"
  );
  if (!ok) return;

  showListError("");
  try {
    await api("/api/operations/" + op.id, { method: "DELETE" });
    if (editingId === op.id) stopEdit(); // удалили то, что было открыто в форме
    await reloadAll();
  } catch (error) {
    showListError("Не удалось удалить: " + error.message);
  }
}

// ---------- Форма операции ----------

function selectedType() {
  return document.querySelector('input[name="type"]:checked').value;
}

function setType(type) {
  document.querySelector('input[name="type"][value="' + type + '"]').checked = true;
}

// Заполняет список категорий нужного типа.
// Выбирает категорию selectedId, если она есть в списке, иначе — «Прочее».
function fillCategories(selectedId) {
  const select = document.getElementById("category");
  const type = selectedType();
  const list = categories.filter((c) => c.type === type);
  const hasSelected = list.some((c) => c.id === selectedId);
  select.innerHTML = "";
  for (const c of list) {
    const option = document.createElement("option");
    option.value = c.id;
    option.textContent = c.name;
    if (hasSelected ? c.id === selectedId : c.name === OTHER_NAME) option.selected = true;
    select.appendChild(option);
  }
}

// Открыть операцию в форме (режим «Редактирование»)
function startEdit(op) {
  editingId = op.id;
  clearErrors();
  setType(op.type);
  fillCategories(op.categoryId);
  document.getElementById("amount").value = amountForInput(op.amount);
  document.getElementById("date").value = op.date;
  document.getElementById("comment").value = op.comment;

  document.getElementById("form-title").textContent = "Редактирование операции";
  document.getElementById("op-submit").textContent = "Сохранить";
  document.getElementById("op-cancel").hidden = false;
  renderOperations(); // подсветить выбранную строку
  document.getElementById("amount").focus();
}

// Вернуть форму в режим добавления (данные на сервере не меняются)
function stopEdit() {
  editingId = null;
  clearErrors();
  setType("expense");
  fillCategories();
  document.getElementById("amount").value = "";
  document.getElementById("date").value = todayIso();
  document.getElementById("comment").value = "";

  document.getElementById("form-title").textContent = "Новая операция";
  document.getElementById("op-submit").textContent = "Добавить";
  document.getElementById("op-cancel").hidden = true;
  renderOperations(); // снять подсветку
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

  const button = document.getElementById("op-submit");
  button.disabled = true;
  try {
    if (editingId === null) {
      await sendJson("/api/operations", "POST", body);
      // Успех: очищаем сумму и комментарий, дата и тип остаются для следующей записи
      document.getElementById("amount").value = "";
      document.getElementById("comment").value = "";
    } else {
      await sendJson("/api/operations/" + editingId, "PUT", body);
      stopEdit();
    }
    await reloadAll();
    document.getElementById("amount").focus();
  } catch (error) {
    showFieldError(error.field, error.message);
  } finally {
    button.disabled = false;
  }
}

// ---------- Категории (левая панель) ----------

function renderCategories() {
  for (const type of ["expense", "income"]) {
    const list = document.getElementById("cats-" + type);
    list.innerHTML = "";
    for (const c of categories.filter((c) => c.type === type)) {
      const item = document.createElement("li");
      item.className = "cat-item";
      if (c.id === editingCatId) item.classList.add("selected");
      item.title = "Нажмите, чтобы изменить";
      item.addEventListener("click", () => startCatEdit(c));

      const dot = document.createElement("span");
      dot.className = "dot";
      dot.style.background = c.color;

      const name = document.createElement("span");
      name.textContent = c.name;

      item.append(dot, name);
      list.appendChild(item);
    }
  }
}

// Загрузить категории заново и перерисовать всё, где они видны
async function reloadCategories() {
  categories = await api("/api/categories");
  renderCategories();
  // В форме операции сохраняем выбранную категорию, если она ещё существует
  fillCategories(Number(document.getElementById("category").value));
  renderOperations(); // новые имена и цвета в списке операций
}

function showCatError(message) {
  document.getElementById("cat-error").textContent = message;
  document.getElementById("cat-name").classList.toggle("invalid", Boolean(message));
}

function startCatEdit(c) {
  editingCatId = c.id;
  showCatError("");
  document.getElementById("cat-name").value = c.name;
  document.getElementById("cat-type").value = c.type;
  document.getElementById("cat-type").disabled = true; // тип категории не меняется
  document.getElementById("cat-color").value = c.color;
  document.getElementById("cat-form-title").textContent = "Изменить категорию";
  document.getElementById("cat-submit").textContent = "Сохранить";
  document.getElementById("cat-delete").hidden = false;
  document.getElementById("cat-cancel").hidden = false;
  renderCategories();
  document.getElementById("cat-name").focus();
}

function stopCatEdit() {
  editingCatId = null;
  showCatError("");
  document.getElementById("cat-name").value = "";
  document.getElementById("cat-type").disabled = false;
  document.getElementById("cat-color").value = DEFAULT_CAT_COLOR;
  document.getElementById("cat-form-title").textContent = "Новая категория";
  document.getElementById("cat-submit").textContent = "Добавить";
  document.getElementById("cat-delete").hidden = true;
  document.getElementById("cat-cancel").hidden = true;
  renderCategories();
}

async function onCatSubmit(event) {
  event.preventDefault();
  const name = document.getElementById("cat-name").value.trim();
  if (name === "") {
    showCatError("Введите название");
    return;
  }

  const body = {
    name: name,
    type: document.getElementById("cat-type").value,
    color: document.getElementById("cat-color").value,
  };

  const button = document.getElementById("cat-submit");
  button.disabled = true;
  try {
    if (editingCatId === null) {
      await sendJson("/api/categories", "POST", body);
    } else {
      await sendJson("/api/categories/" + editingCatId, "PUT", body);
    }
    stopCatEdit();
    await reloadCategories();
  } catch (error) {
    showCatError(error.message); // например, «Такая категория уже есть»
  } finally {
    button.disabled = false;
  }
}

async function onCatDelete() {
  const category = categories.find((c) => c.id === editingCatId);
  if (!category) return;
  const ok = await askConfirm("Удалить категорию «" + category.name + "»?");
  if (!ok) return;

  try {
    await api("/api/categories/" + category.id, { method: "DELETE" });
    stopCatEdit();
    await reloadCategories();
  } catch (error) {
    showCatError(error.message); // «В категории есть операции — удалить нельзя»
  }
}

// ---------- Запуск ----------

async function init() {
  document.getElementById("date").value = todayIso();
  document.getElementById("op-form").addEventListener("submit", onSubmit);
  document.getElementById("op-cancel").addEventListener("click", stopEdit);

  // Смена типа: категория сбрасывается на «Прочее» нужного типа
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

  // Кнопки окна подтверждения: close(значение) закрывает окно и запоминает ответ
  const dialog = document.getElementById("confirm-dialog");
  document.getElementById("confirm-ok").addEventListener("click", () => dialog.close("ok"));
  document.getElementById("confirm-cancel").addEventListener("click", () => dialog.close("cancel"));

  document.getElementById("cat-form").addEventListener("submit", onCatSubmit);
  document.getElementById("cat-cancel").addEventListener("click", stopCatEdit);
  document.getElementById("cat-delete").addEventListener("click", onCatDelete);
  document.getElementById("cat-name").addEventListener("input", () => showCatError(""));

  try {
    categories = await api("/api/categories");
    renderCategories();
    fillCategories();
    await reloadAll();
  } catch (error) {
    showListError("Не удалось загрузить данные: " + error.message);
  }
}

init();
