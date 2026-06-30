// =====================================================================
//  Расписание · ServGo — новый рендер (день/неделя, now-линия,
//  лист быстрых действий, drag&drop переноса, светлая/тёмная тема).
//  Использует существующие эндпоинты:
//    GET  /api/analytics/businesses
//    GET  /api/analytics/schedule?business_id&start_date&end_date
//    POST /api/booking/{id}/status            { status }
//    POST /api/admin/booking                  (создание)
//    POST /api/admin/booking/{id}/reschedule  { date, time, employee_id }  <-- НОВЫЙ (см. server_patch.py)
//    GET  /api/client/business/{id}/calculate-price (venue_rental)
// =====================================================================

let tg = null;
let businesses = [];
let selectedBusinessId = null;

let viewMode = 'day';        // 'day' | 'week'
let dayOffset = 0;
let weekOffset = 0;

let workingHours = { start: 8, end: 22 };
let bookingInterval = 30;
let canCreate = true;
let scheduleData = [];
let employees = [];
let services = [];
let additionalServices = [];
let clients = [];
let businessType = '';
let activeEmp = 'all';       // 'all' | employee_id
let searchQuery = '';
let selectedBookingId = null;
let moveMode = false;

const PXH = () => parseInt(getComputedStyle(document.documentElement).getPropertyValue('--pxh')) || 56;

const STATUS = {
  confirmed:  { label: 'Подтверждено', color: 'var(--st-confirmed)' },
  pending:    { label: 'Ожидание',     color: 'var(--st-pending)' },
  completed:  { label: 'Завершено',    color: 'var(--st-completed)' },
  cancelled:  { label: 'Отменено',     color: 'var(--st-cancelled)' },
  pending_prepayment: { label: 'Предоплата', color: 'var(--st-prepayment)' },
  prepayment_sent:    { label: 'Оплата отправлена', color: 'var(--st-prepayment)' },
};
const STATUS_HEX = {
  confirmed: '#2ea6ff', pending: '#f5a623', completed: '#30d158',
  cancelled: '#8d99a8', pending_prepayment: '#a78bfa', prepayment_sent: '#a78bfa',
};
const MONTHS = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
const WDAYS = ['воскресенье','понедельник','вторник','среда','четверг','пятница','суббота'];
const DNAMES = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];

/* ---------- helpers ---------- */
function toMin(t) { const [h, m] = (t || '0:0').split(':').map(Number); return h * 60 + m; }
function fmtMin(min) { const h = Math.floor(min / 60), m = min % 60; return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0'); }
function hexA(hex, a) { const n = parseInt(hex.slice(1), 16); return `rgba(${(n>>16)&255},${(n>>8)&255},${n&255},${a})`; }
function isoDate(d) { return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
function esc(t) { if (!t) return ''; const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }
function statusHex(s) { return STATUS_HEX[s] || '#2ea6ff'; }

/* =====================================================================
   Init
   ===================================================================== */
document.addEventListener('DOMContentLoaded', () => setTimeout(initApp, 100));

async function initApp() {
  tg = window.Telegram?.WebApp;
  if (tg) {
    tg.ready(); tg.expand();
    applyTheme(tg.colorScheme === 'light' ? 'light' : 'dark');
  } else {
    applyTheme(localStorage.getItem('schedule_theme') || 'dark');
  }

  if (!tg?.initData) {
    const b = document.getElementById('backBtn');
    if (b) { b.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'; b.setAttribute('onclick', 'webLogout()'); b.title = 'Выйти'; }
  }

  const urlRole = new URLSearchParams(location.search).get('role');
  if (urlRole === 'admin') { viewMode = 'day'; canCreate = false; }

  document.getElementById('searchInput').addEventListener('input', (e) => {
    searchQuery = e.target.value;
    document.getElementById('searchClear').style.display = searchQuery ? '' : 'none';
    render();
  });

  document.getElementById('businessSelect').addEventListener('change', (e) => {
    selectedBusinessId = e.target.value;
    if (selectedBusinessId) loadSchedule();
  });

  initDrag();
  initClientAutocomplete();
  await loadBusinesses();
}

/* ---------- theme ---------- */
function applyTheme(theme) {
  document.body.setAttribute('data-theme', theme);
  localStorage.setItem('schedule_theme', theme);
  document.getElementById('themeIconDark').style.display = theme === 'dark' ? '' : 'none';
  document.getElementById('themeIconLight').style.display = theme === 'light' ? '' : 'none';
}
function toggleTheme() {
  applyTheme(document.body.getAttribute('data-theme') === 'light' ? 'dark' : 'light');
}

/* =====================================================================
   API
   ===================================================================== */
async function apiRequest(endpoint) {
  const headers = { 'Content-Type': 'application/json' };
  if (tg?.initData) headers['X-Telegram-Init-Data'] = tg.initData;
  const resp = await fetch(endpoint, { method: 'GET', headers, credentials: 'same-origin' });
  const data = await resp.json();
  if (!resp.ok) {
    if (resp.status === 401 && !tg?.initData) { location.href = '/login?to=/schedule'; return { error: 'redirect' }; }
    return { error: data.error || `HTTP ${resp.status}` };
  }
  return data;
}

async function loadBusinesses() {
  try {
    const data = await apiRequest('/api/analytics/businesses');
    if (data.error) { if (data.error !== 'redirect') showError(data.error === 'Unauthorized' ? 'Не удалось авторизоваться. Войдите через /login или откройте через Telegram.' : data.error); return; }
    if (data.businesses && data.businesses.length) {
      businesses = data.businesses;
      if (data.is_owner) viewMode = 'day';
      const sel = document.getElementById('businessSelect');
      sel.innerHTML = '<option value="">Бизнес</option>';
      businesses.forEach(b => { const o = document.createElement('option'); o.value = b.id; o.textContent = b.name; sel.appendChild(o); });
      selectedBusinessId = businesses[0].id; sel.value = selectedBusinessId;
      document.getElementById('businessName').textContent = businesses[0].name;
      await loadSchedule();
      startAutoRefresh();
    } else showError('Нет доступных бизнесов');
  } catch (e) { console.error(e); showError('Ошибка загрузки данных'); }
}

function currentRange() {
  const today = new Date();
  if (viewMode === 'day') {
    const d = new Date(today); d.setDate(today.getDate() + dayOffset); d.setHours(0,0,0,0);
    return { start: isoDate(d), end: isoDate(d) };
  }
  const dow = today.getDay(); const mondayOff = dow === 0 ? -6 : 1 - dow;
  const ws = new Date(today); ws.setDate(today.getDate() + mondayOff + weekOffset * 7); ws.setHours(0,0,0,0);
  const we = new Date(ws); we.setDate(ws.getDate() + 6);
  return { start: isoDate(ws), end: isoDate(we) };
}

async function loadSchedule() {
  if (!selectedBusinessId) return;
  try {
    const { start, end } = currentRange();
    const data = await apiRequest(`/api/analytics/schedule?business_id=${selectedBusinessId}&start_date=${start}&end_date=${end}`);
    if (data.error) { showError(data.error); return; }
    scheduleData = data.bookings || [];
    employees = data.employees || [];
    services = data.services || [];
    additionalServices = data.additional_services || [];
    clients = data.clients || [];
    businessType = data.business_type || '';
    workingHours = data.working_hours || { start: 8, end: 22 };
    bookingInterval = data.booking_interval || 30;
    canCreate = data.can_create_booking !== false;
    const biz = businesses.find(b => String(b.id) === String(selectedBusinessId));
    if (biz) document.getElementById('businessName').textContent = biz.name;

    document.getElementById('loading').style.display = 'none';
    document.getElementById('mainContent').style.display = 'flex';
    document.getElementById('fabAdd').style.display = canCreate ? 'flex' : 'none';
    render();
  } catch (e) { console.error(e); showError('Ошибка загрузки расписания'); }
}

let _refreshTimer = null;
function startAutoRefresh() { if (_refreshTimer) clearInterval(_refreshTimer); _refreshTimer = setInterval(() => { if (selectedBusinessId && !moveMode && !selectedBookingId && document.getElementById('newBookingModal').classList.contains('hidden')) loadSchedule(); }, 20000); }

/* =====================================================================
   Navigation / view
   ===================================================================== */
function setViewMode(mode) {
  if (viewMode === mode) return;
  viewMode = mode;
  document.getElementById('segDay').classList.toggle('active', mode === 'day');
  document.getElementById('segWeek').classList.toggle('active', mode === 'week');
  loadSchedule();
}
function navigate(dir) { if (viewMode === 'day') dayOffset += dir; else weekOffset += dir; loadSchedule(); }
function goToToday() { dayOffset = 0; weekOffset = 0; loadSchedule(); }
function clearSearch() { searchQuery = ''; document.getElementById('searchInput').value = ''; document.getElementById('searchClear').style.display = 'none'; render(); }

function workStart() { return workingHours?.start ?? 8; }
function workEnd() { return workingHours?.end ?? 22; }

function matchesSearch(b) {
  const q = searchQuery.trim().toLowerCase(); if (!q) return true;
  const qd = q.replace(/\D/g, '');
  return (b.client_name || '').toLowerCase().includes(q)
    || (b.service_name || '').toLowerCase().includes(q)
    || (qd.length > 0 && (b.client_phone || '').replace(/\D/g, '').includes(qd));
}

/* =====================================================================
   Render
   ===================================================================== */
function render() {
  document.getElementById('segDay').classList.toggle('active', viewMode === 'day');
  document.getElementById('segWeek').classList.toggle('active', viewMode === 'week');
  renderChips();
  renderNav();
  renderLegend();
  renderSummary();
  if (viewMode === 'day') renderDay(); else renderWeek();
}

function renderChips() {
  const c = document.getElementById('empChips');
  const items = [{ id: 'all', name: 'Все', color: null }, ...employees.map(e => ({ id: e.id, name: e.name, color: empColor(e.id) }))];
  c.innerHTML = items.map(it => {
    const active = activeEmp === it.id;
    const idArg = it.id === 'all' ? "'all'" : it.id;
    if (it.color) {
      const style = active ? `background:${it.color};border-color:${it.color};color:#04121f;` : '';
      const dot = active ? '' : `<span class="chip-dot" style="background:${it.color}"></span>`;
      return `<button class="chip${active ? ' active' : ''}" style="${style}" onclick="selectEmp(${idArg})">${dot}${esc(it.name)}</button>`;
    }
    return `<button class="chip${active ? ' active' : ''}" onclick="selectEmp(${idArg})">${esc(it.name)}</button>`;
  }).join('');
}
function selectEmp(id) { activeEmp = (activeEmp === id) ? 'all' : id; render(); }

function renderNav() {
  const main = document.getElementById('navMain'), sub = document.getElementById('navSub');
  const today = new Date();
  if (viewMode === 'day') {
    const d = new Date(today); d.setDate(today.getDate() + dayOffset);
    main.textContent = dayOffset === 0 ? 'Сегодня' : dayOffset === 1 ? 'Завтра' : dayOffset === -1 ? 'Вчера' : `${d.getDate()} ${MONTHS[d.getMonth()].slice(0,3)}`;
    sub.textContent = `${d.getDate()} ${MONTHS[d.getMonth()].slice(0,3)}`;        // компактная подпись в одну строку
    sub.style.display = '';
  } else {
    const { start, end } = currentRange();
    const ws = new Date(start), we = new Date(end);
    main.textContent = weekOffset === 0 ? 'Эта неделя' : weekOffset === 1 ? 'След. неделя' : weekOffset === -1 ? 'Прош. неделя' : `${ws.getDate()} ${MONTHS[ws.getMonth()].slice(0,3)} – ${we.getDate()} ${MONTHS[we.getMonth()].slice(0,3)}`;
    sub.textContent = '';                                                          // диапазон недели слишком длинный для второй строки
    sub.style.display = 'none';
  }
}

let detailsOpen = false;
function toggleDetails() {
  detailsOpen = !detailsOpen;
  document.getElementById('detailsPanel').hidden = !detailsOpen;
  document.getElementById('detailsToggle').classList.toggle('open', detailsOpen);
}

function renderLegend() {
  const used = ['confirmed', 'pending', 'completed', 'cancelled', 'pending_prepayment'];
  document.getElementById('legend').innerHTML = used.map(s =>
    `<div class="item"><span class="swatch" style="background:${statusHex(s)}"></span><span>${STATUS[s].label}</span></div>`
  ).join('');
}

function renderSummary() {
  let scope = scheduleData.filter(b => activeEmp === 'all' || b.employee_id === activeEmp);
  const active = scope.filter(b => b.status !== 'cancelled');
  const revenue = active.reduce((s, b) => s + (b.price || 0), 0);
  const bookedMin = active.reduce((s, b) => s + (b.duration || 60), 0);
  const days = viewMode === 'week' ? 7 : 1;
  const cap = (workEnd() - workStart()) * 60 * (activeEmp === 'all' ? Math.max(1, employees.length) : 1) * days;
  const load = cap ? Math.round(bookedMin / cap * 100) : 0;
  document.getElementById('summary').innerHTML = `
    <div class="tile"><div class="num">${active.length}</div><div class="lbl">записей</div></div>
    <div class="tile"><div class="num">${revenue.toLocaleString('ru-RU')}</div><div class="lbl">выручка ₽</div></div>
    <div class="tile"><div class="num">${load}%</div><div class="lbl">загрузка</div></div>`;
}

function hoursMarkup() {
  let h = '';
  for (let i = workStart(); i <= workEnd(); i++) h += `<div class="tl-hour" style="top:${(i - workStart()) * PXH()}px">${i}:00</div>`;
  return h;
}
function totalHeight() { return (workEnd() - workStart()) * PXH(); }

function emptyMarkup() {
  return `<div class="empty-state">
    <div class="ico"><svg width="30" height="30" viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="16" rx="3" stroke="currentColor" stroke-width="2"/><path d="M3 9h18M8 3v4M16 3v4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></div>
    <div><div class="t1">Нет записей</div><div class="t2">На этот период записей пока нет</div></div>
    ${canCreate ? '<button class="add" onclick="openNewBookingModal()">+ Добавить запись</button>' : ''}
  </div>`;
}

/* ---------- DAY ---------- */
function renderDay() {
  const head = document.getElementById('colHeader');
  const tl = document.getElementById('timeline');
  const emps = employees;
  head.style.gridTemplateColumns = `var(--gutter) repeat(${Math.max(1, emps.length)}, 1fr)`;
  head.innerHTML = `<div class="gutter-cell"></div>` + emps.map(e => {
    const dim = activeEmp !== 'all' && activeEmp !== e.id;
    return `<div class="emp-cap" style="opacity:${dim ? .35 : 1}" onclick="selectEmp(${e.id})">
      <span class="cap" style="background:${empColor(e.id)}"></span></div>`;
  }).join('');

  const dayBookings = scheduleData;
  if (!dayBookings.length) { tl.innerHTML = emptyMarkup(); return; }

  let cols = emps.map(e => {
    const dim = activeEmp !== 'all' && activeEmp !== e.id;
    const cards = dayBookings.filter(b => b.employee_id === e.id).map(b => dayCard(b)).join('');
    return `<div class="tl-col" style="opacity:${dim ? .32 : 1}">${cards}</div>`;
  }).join('');

  const today = new Date(); today.setHours(0,0,0,0);
  const curDay = new Date(today); curDay.setDate(today.getDate() + dayOffset);
  const showNow = isoDate(curDay) === isoDate(new Date());
  const nowLine = showNow ? nowLineMarkup() : '';

  tl.innerHTML = `<div class="tl-inner" style="height:${totalHeight()}px">
    <div class="tl-gutter">${hoursMarkup()}</div>
    <div class="tl-cols" id="dayCols" style="grid-template-columns:repeat(${Math.max(1, emps.length)},1fr)">${cols}</div>
    ${nowLine}
  </div>`;
}

function dayCard(b) {
  const sm = toMin(b.time || b.time_start || '0:0');
  const dur = b.duration || 60;
  const top = (sm - workStart() * 60) / 60 * PXH();
  const height = Math.max(26, dur / 60 * PXH() - 3);
  const hex = statusHex(b.status);
  const cancelled = b.status === 'cancelled';
  const faded = searchQuery && !matchesSearch(b);
  const op = faded ? .22 : (cancelled ? .6 : 1);
  const showSvc = height >= 44, showTime = height >= 58;
  return `<div class="tl-card ${cancelled ? 'cancelled' : ''}" data-id="${b.id}"
      style="top:${top}px;height:${height}px;opacity:${op};background:${hexA(hex,.16)};border:1px solid ${hexA(hex,.5)};border-left:3px solid ${hex}">
    <div class="c-name">${esc(b.client_name || 'Клиент')}</div>
    ${showSvc ? `<div class="c-svc">${esc(b.service_name || '')}</div>` : ''}
    ${showTime ? `<div class="c-time">${b.time || ''}–${fmtMin(sm + dur)}</div>` : ''}
  </div>`;
}

/* ---------- WEEK ---------- */
function renderWeek() {
  const head = document.getElementById('colHeader');
  const tl = document.getElementById('timeline');
  const { start } = currentRange();
  const ws = new Date(start);
  const today = new Date();
  head.style.gridTemplateColumns = `var(--gutter) repeat(7, 1fr)`;
  let headHtml = `<div class="gutter-cell"></div>`;
  const days = [];
  for (let d = 0; d < 7; d++) {
    const cd = new Date(ws); cd.setDate(ws.getDate() + d);
    const isToday = isoDate(cd) === isoDate(today);
    days.push({ date: cd, isToday });
    headHtml += `<div class="wday-head ${isToday ? 'today' : ''}"><span class="wd">${DNAMES[d]}</span><span class="dt">${cd.getDate()}</span></div>`;
  }
  head.innerHTML = headHtml;

  const inWeek = scheduleData.filter(b => activeEmp === 'all' || b.employee_id === activeEmp);
  if (!inWeek.filter(b => b.status !== 'cancelled').length) { tl.innerHTML = emptyMarkup(); return; }

  let cols = days.map(({ date, isToday }) => {
    let db = inWeek.filter(b => b.date === isoDate(date) && matchesSearch(b));
    db.sort((a, b) => toMin(a.time) - toMin(b.time));
    // группируем пересекающиеся записи в кластеры
    const clusters = [];
    db.forEach(b => { const s = toMin(b.time), e = s + (b.duration || 60); const last = clusters[clusters.length - 1];
      if (last && s < last.end) { last.end = Math.max(last.end, e); last.items.push(b); }
      else clusters.push({ start: s, end: e, items: [b] }); });
    let cards = '';
    clusters.forEach(cl => {
      const lEnds = [];
      cl.items.forEach(b => { const s = toMin(b.time), e = s + (b.duration || 60); let l = lEnds.findIndex(end => end <= s); if (l === -1) { l = lEnds.length; lEnds.push(e); } else lEnds[l] = e; b._lane = l; });
      const clLanes = Math.max(1, lEnds.length);
      if (clLanes >= 3) {
        cards += weekCountBlock(cl, isoDate(date));
      } else {
        cards += cl.items.map(b => weekCard(b, clLanes)).join('');
      }
    });
    return `<div class="tl-col ${isToday ? 'today' : ''}">${cards}</div>`;
  }).join('');

  const showNow = weekOffset === 0;
  tl.innerHTML = `<div class="tl-inner" style="height:${totalHeight()}px">
    <div class="tl-gutter">${hoursMarkup()}</div>
    <div class="tl-cols" style="grid-template-columns:repeat(7,1fr)">${cols}</div>
    ${showNow ? nowLineMarkup(true) : ''}
  </div>`;
}

function weekCard(b, lanes) {
  const sm = toMin(b.time);
  const dur = b.duration || 60;
  const top = (sm - workStart() * 60) / 60 * PXH();
  const height = Math.max(16, dur / 60 * PXH() - 2);
  const hex = statusHex(b.status);
  const w = 100 / lanes, left = b._lane * w;
  const cancelled = b.status === 'cancelled';
  const showLabel = w > 32 && height >= 22;
  return `<div class="wk-card" data-id="${b.id}" onclick="showBookingDetails(${b.id})"
      style="top:${top}px;height:${height}px;left:calc(${left}% + 1px);width:calc(${w}% - 2px);background:${hexA(hex,.9)};opacity:${cancelled ? .45 : 1}">
    ${showLabel ? esc((b.client_name || 'Клиент').split(' ')[0]) : ''}</div>`;
}

// агрегированный блок «N записей» для перегруженного времени (3+ одновременно)
function weekCountBlock(cl, dateStr) {
  const top = (cl.start - workStart() * 60) / 60 * PXH();
  const height = Math.max(30, (cl.end - cl.start) / 60 * PXH() - 2);
  const n = cl.items.length;
  return `<div class="wk-count" onclick="drillToDay('${dateStr}')"
      style="top:${top}px;height:${height}px">
    <span class="num">${n}</span><span class="lbl">записей</span></div>`;
}

// переход из недели в день по тапу на счётчик
function drillToDay(dateStr) {
  const target = new Date(dateStr + 'T00:00:00');
  const today = new Date(); today.setHours(0, 0, 0, 0);
  dayOffset = Math.round((target - today) / 86400000);
  viewMode = 'day';
  document.getElementById('segDay').classList.add('active');
  document.getElementById('segWeek').classList.remove('active');
  loadSchedule();
}

function nowLineMarkup(week) {
  const now = new Date();
  const min = now.getHours() * 60 + now.getMinutes();
  if (min < workStart() * 60 || min > workEnd() * 60) return '';
  const top = (min - workStart() * 60) / 60 * PXH();
  return `<div class="now-line" style="top:${top}px">
    <div class="bar"></div><div class="knob"></div>
    ${week ? '' : `<div class="lbl">${fmtMin(min)}</div>`}
  </div>`;
}

function empColor(id) {
  const palette = ['#ff6b9d', '#4dd4ff', '#ffd166', '#b388ff', '#30d158', '#ff9f6b', '#7cc4ff', '#f59ed4'];
  const idx = employees.findIndex(e => e.id === id);
  return palette[(idx < 0 ? 0 : idx) % palette.length];
}

/* =====================================================================
   Booking details / quick actions (bottom sheet)
   ===================================================================== */
function showBookingDetails(id) {
  const b = scheduleData.find(x => x.id === id);
  if (!b) return;
  selectedBookingId = id;
  moveMode = false; renderMoveHint();
  const emp = employees.find(e => e.id === b.employee_id);
  const meta = STATUS[b.status] || STATUS.confirmed;
  const sm = toMin(b.time || '0:0'), dur = b.duration || 60;
  const hex = statusHex(b.status);
  const actions = statusActions(b);
  document.getElementById('sheetRoot').innerHTML = `
    <div class="scrim" onclick="closeSheet()"></div>
    <div class="sheet">
      <div class="sheet-handle"></div>
      <div class="sheet-head">
        <span class="sheet-ava" style="background:${empColor(b.employee_id)}">${esc((b.client_name||'?')[0])}</span>
        <div style="flex:1;min-width:0;"><div class="nm">${esc(b.client_name || 'Клиент')}</div><div class="svc">${esc(b.service_name || '')}</div></div>
        <span class="status-badge" style="background:${hexA(hex,.18)};color:${hex}">${meta.label}</span>
      </div>
      <div class="sheet-grid">
        <div class="f"><div class="k">Время</div><div class="v">${b.time || ''}–${fmtMin(sm + dur)}</div></div>
        <div class="f"><div class="k">Мастер</div><div class="v">${esc(emp ? emp.name : '—')}</div></div>
        <div class="f"><div class="k">Телефон</div><div class="v">${esc(b.client_phone || '—')}</div></div>
        <div class="f"><div class="k">Стоимость</div><div class="v">${b.price ? b.price.toLocaleString('ru-RU') + ' ₽' : '—'}</div></div>
        ${b.comment ? `<div class="f" style="min-width:100%"><div class="k">Комментарий</div><div class="v">${esc(b.comment)}</div></div>` : ''}
      </div>
      <div class="sheet-actions">${actions}</div>
    </div>`;
}

function statusActions(b) {
  const s = b.status;
  let html = '';
  if (s === 'pending_prepayment' || s === 'prepayment_sent') {
    html = `<button class="act confirm" onclick="updateStatus(${b.id},'confirmed')">✓ Подтвердить оплату</button>
            <button class="act move" onclick="startMove(${b.id})">⇅ Перенести</button>
            <button class="act cancel" style="grid-column:1/-1" onclick="updateStatus(${b.id},'cancelled')">✕ Отменить</button>`;
  } else if (s === 'pending' || s === 'confirmed') {
    html = `${s === 'pending' ? `<button class="act confirm" onclick="updateStatus(${b.id},'confirmed')">✓ Подтвердить</button>` : ''}
            <button class="act complete" onclick="updateStatus(${b.id},'completed')">✓ Завершить</button>
            <button class="act move" onclick="startMove(${b.id})">⇅ Перенести</button>
            <button class="act cancel" onclick="updateStatus(${b.id},'cancelled')">✕ Отменить</button>`;
  } else if (s === 'cancelled') {
    html = `<button class="act confirm" style="grid-column:1/-1" onclick="updateStatus(${b.id},'confirmed')">↩ Восстановить</button>`;
  }
  return html;
}

function closeSheet() { selectedBookingId = null; document.getElementById('sheetRoot').innerHTML = ''; }

async function updateStatus(id, status) {
  const labels = { confirmed: 'подтвердить', completed: 'завершить', cancelled: 'отменить' };
  if (!confirm(`Вы уверены, что хотите ${labels[status] || 'изменить'} эту запись?`)) return;
  try {
    const resp = await fetch(`/api/booking/${id}/status`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': tg?.initData || '' }, credentials: 'same-origin', body: JSON.stringify({ status }) });
    const data = await resp.json();
    if (data.success) { closeSheet(); await loadSchedule(); notify('Статус записи изменён'); }
    else alert(data.error || 'Ошибка при изменении статуса');
  } catch (e) { console.error(e); alert('Ошибка при изменении статуса'); }
}

/* =====================================================================
   Move / drag&drop → POST /api/admin/booking/{id}/reschedule
   ===================================================================== */
function startMove(id) { selectedBookingId = id; closeSheet(); selectedBookingId = id; moveMode = true; renderMoveHint(); }
function cancelMove() { moveMode = false; selectedBookingId = null; renderMoveHint(); }
function renderMoveHint() {
  document.getElementById('moveHintRoot').innerHTML = moveMode
    ? `<div class="move-hint">Перетащите карточку на новое время · <a onclick="cancelMove()">отмена</a></div>` : '';
}

let drag = null;
function initDrag() {
  document.addEventListener('pointerdown', (e) => {
    const card = e.target.closest('.tl-card');
    if (!card || viewMode !== 'day' || !canCreate) return;
    const id = parseInt(card.dataset.id);
    const b = scheduleData.find(x => x.id === id);
    if (!b || b.status === 'cancelled' || b.status === 'completed') return;
    drag = { id, card, startX: e.clientX, startY: e.clientY,
      origTop: (toMin(b.time) - workStart() * 60) / 60 * PXH(), moved: false,
      cols: card.closest('.tl-cols') };
    card.style.transition = 'none';
  });
  document.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.startX, dy = e.clientY - drag.startY;
    if (!drag.moved && Math.abs(dx) + Math.abs(dy) > 6) drag.moved = true;
    if (drag.moved) {
      e.preventDefault();
      drag.card.style.transform = `translate(${dx}px,${dy}px)`;
      drag.card.style.zIndex = '50';
      drag.card.style.boxShadow = '0 18px 32px -10px rgba(0,0,0,.5)';
      drag.card.style.opacity = '.95';
    }
  }, { passive: false });
  document.addEventListener('pointerup', (e) => {
    if (!drag) return;
    const d = drag; drag = null;
    if (!d.moved) { showBookingDetails(d.id); return; }
    const dy = e.clientY - d.startY;
    // целевой мастер по X
    let empId = null;
    const cols = d.cols ? [...d.cols.children] : [];
    if (cols.length) {
      const r = d.cols.getBoundingClientRect();
      const idx = Math.max(0, Math.min(employees.length - 1, Math.floor((e.clientX - r.left) / (r.width / employees.length))));
      empId = employees[idx]?.id ?? null;
    }
    let startMin = workStart() * 60 + (d.origTop + dy) / PXH() * 60;
    startMin = Math.round(startMin / 15) * 15;
    startMin = Math.max(workStart() * 60, Math.min(workEnd() * 60 - 15, startMin));
    d.card.style.transform = ''; d.card.style.zIndex = ''; d.card.style.boxShadow = ''; d.card.style.opacity = '';
    reschedule(d.id, startMin, empId);
  });
}

async function reschedule(id, startMin, empId) {
  const b = scheduleData.find(x => x.id === id); if (!b) return;
  const today = new Date(); const d = new Date(today); d.setDate(today.getDate() + dayOffset);
  const payload = { date: isoDate(d), time: fmtMin(startMin) };
  if (empId != null && empId !== b.employee_id) payload.employee_id = empId;
  // оптимистично
  b.time = fmtMin(startMin); if (payload.employee_id != null) b.employee_id = empId;
  render();
  try {
    const resp = await fetch(`/api/admin/booking/${id}/reschedule`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': tg?.initData || '' }, credentials: 'same-origin', body: JSON.stringify(payload) });
    const data = await resp.json();
    moveMode = false; renderMoveHint();
    if (!data.success) { alert(data.error || 'Не удалось перенести запись'); await loadSchedule(); }
    else { await loadSchedule(); notify('Запись перенесена'); }
  } catch (e) { console.error(e); alert('Ошибка переноса'); await loadSchedule(); }
}

function notify(msg) { if (tg) tg.showPopup({ title: 'Готово', message: msg, buttons: [{ type: 'ok' }] }); }

/* =====================================================================
   New booking modal  (POST /api/admin/booking — без изменений API)
   ===================================================================== */
function openNewBookingModal(dateStr, timeStr) {
  if (!selectedBusinessId) { alert('Сначала выберите бизнес'); return; }
  const isVenue = businessType === 'venue_rental';
  document.getElementById('nbEmployeeLabel').textContent = isVenue ? 'Зал / Помещение' : 'Мастер';

  const svcSel = document.getElementById('nbService');
  svcSel.innerHTML = '<option value="">Выберите услугу</option>';
  services.forEach(s => {
    const priceStr = (!isVenue && s.price) ? ` · ${s.price} ₽` : '';
    const durStr = s.duration ? ` · ${s.duration} мин` : '';
    const o = document.createElement('option'); o.value = s.id; o.textContent = `${s.name}${durStr}${priceStr}`; svcSel.appendChild(o);
  });

  const addGroup = document.getElementById('nbAdditionalServicesGroup');
  const addBox = document.getElementById('nbAdditionalServices');
  if (isVenue && additionalServices.length) {
    addBox.innerHTML = '';
    additionalServices.forEach(s => { const l = document.createElement('label'); l.className = 'additional-service-item'; l.innerHTML = `<input type="checkbox" class="nb-add-svc" value="${s.id}"> ${esc(s.name)}${s.price ? ' — ' + s.price + ' ₽' : ''}`; addBox.appendChild(l); });
    addGroup.style.display = '';
  } else addGroup.style.display = 'none';

  svcSel.onchange = () => { updateEmployeeOptions(isVenue); if (isVenue) calcPrice(); };
  updateEmployeeOptions(isVenue);

  const today = new Date(); const d = new Date(today); d.setDate(today.getDate() + dayOffset);
  document.getElementById('nbDate').value = dateStr || isoDate(d);
  document.getElementById('nbTime').value = timeStr || '12:00';
  if (typeof activeEmp === 'number') document.getElementById('nbEmployee').value = activeEmp;

  const pi = document.getElementById('nbPriceInfo'); pi.style.display = 'none';
  ['nbEmployee', 'nbTime'].forEach(idn => { const el = document.getElementById(idn); el.oninput = () => { if (isVenue) calcPrice(); }; el.onchange = el.oninput; });
  if (isVenue) setTimeout(calcPrice, 50);

  document.getElementById('nbComment').value = '';
  document.getElementById('nbClientName').value = '';
  document.getElementById('nbClientPhone').value = '+7 9';
  const sb = document.getElementById('nbSubmitBtn'); sb.disabled = false; sb.textContent = 'Создать запись';
  document.getElementById('newBookingModal').classList.remove('hidden');
  setTimeout(() => document.getElementById('nbClientName').focus(), 100);
}

function updateEmployeeOptions(isVenue) {
  const svc = document.getElementById('nbService'); const emp = document.getElementById('nbEmployee');
  const prev = emp.value;
  emp.innerHTML = `<option value="">${isVenue ? 'Любой свободный зал' : 'Любой свободный'}</option>`;
  const sid = parseInt(svc.value); let allowed = null;
  if (sid) { const s = services.find(x => x.id === sid); if (s && s.employee_ids) allowed = s.employee_ids; }
  employees.forEach(e => { if (allowed && !allowed.includes(e.id)) return; const o = document.createElement('option'); o.value = e.id; o.textContent = e.name; emp.appendChild(o); });
  if (prev && [...emp.options].some(o => o.value === prev)) emp.value = prev;
  else if (typeof activeEmp === 'number' && [...emp.options].some(o => o.value == activeEmp)) emp.value = activeEmp;
}

function closeNewBookingModal() { document.getElementById('newBookingModal').classList.add('hidden'); }

async function calcPrice() {
  if (businessType !== 'venue_rental') return;
  const empId = document.getElementById('nbEmployee').value, t = document.getElementById('nbTime').value, dt = document.getElementById('nbDate').value, sid = document.getElementById('nbService').value;
  const pi = document.getElementById('nbPriceInfo');
  if (!empId || !t || !dt || !sid) { pi.style.display = 'none'; return; }
  const svc = services.find(s => s.id === parseInt(sid)); if (!svc) { pi.style.display = 'none'; return; }
  try {
    const headers = { 'Content-Type': 'application/json' }; if (tg?.initData) headers['X-Telegram-Init-Data'] = tg.initData;
    const resp = await fetch(`/api/client/business/${selectedBusinessId}/calculate-price?employee_id=${empId}&time=${t}&duration=${svc.duration}&date=${dt}`, { headers, credentials: 'same-origin' });
    const data = await resp.json();
    if (data.has_time_price && data.total > 0) { pi.style.display = 'flex'; pi.innerHTML = `<span class="sub">${svc.duration} мин</span><span class="val">${data.total} ₽</span>`; }
    else if (svc.price) { pi.style.display = 'flex'; pi.innerHTML = `<span class="sub">${svc.duration || ''} мин</span><span class="val">${svc.price} ₽</span>`; }
    else pi.style.display = 'none';
  } catch (e) { pi.style.display = 'none'; }
}

async function submitNewBooking(ev) {
  ev.preventDefault();
  const sb = document.getElementById('nbSubmitBtn'); sb.disabled = true; sb.textContent = 'Создание…';
  const name = document.getElementById('nbClientName').value.trim();
  const rawPhone = document.getElementById('nbClientPhone').value.trim();
  const phone = (rawPhone === '+7 9' || rawPhone === '+7') ? '' : rawPhone;
  const sid = document.getElementById('nbService').value, eid = document.getElementById('nbEmployee').value;
  const date = document.getElementById('nbDate').value, time = document.getElementById('nbTime').value;
  const comment = document.getElementById('nbComment').value.trim();
  const addIds = [...document.querySelectorAll('.nb-add-svc:checked')].map(c => parseInt(c.value));
  if (!name || !sid || !date || !time) { alert('Заполните все обязательные поля'); sb.disabled = false; sb.textContent = 'Создать запись'; return; }
  try {
    const headers = { 'Content-Type': 'application/json' }; if (tg?.initData) headers['X-Telegram-Init-Data'] = tg.initData;
    const resp = await fetch('/api/admin/booking', { method: 'POST', headers, credentials: 'same-origin', body: JSON.stringify({ business_id: parseInt(selectedBusinessId), service_id: parseInt(sid), employee_id: eid ? parseInt(eid) : null, date, time, client_name: name, client_phone: phone, additional_service_ids: addIds, notes: comment || null }) });
    const data = await resp.json();
    if (data.success) { closeNewBookingModal(); await loadSchedule(); notify('Запись создана'); }
    else { alert(data.error || 'Ошибка при создании записи'); sb.disabled = false; sb.textContent = 'Создать запись'; }
  } catch (e) { console.error(e); alert('Ошибка при создании записи'); sb.disabled = false; sb.textContent = 'Создать запись'; }
}

/* ---------- client autocomplete ---------- */
let selectedClientId = null;
function initClientAutocomplete() {
  const nameInput = document.getElementById('nbClientName');
  const phoneInput = document.getElementById('nbClientPhone');
  if (!nameInput) return;
  const onType = (input, byPhone) => {
    selectedClientId = null;
    const q = input.value.trim().toLowerCase();
    if ((byPhone ? q.replace(/\D/g, '').length : q.length) < (byPhone ? 2 : 1)) { hideSuggestions(); return; }
    const matches = clients.filter(c => (c.name && c.name.toLowerCase().includes(q)) || (c.phone && c.phone.replace(/\D/g, '').includes(q.replace(/\D/g, '')))).slice(0, 8);
    showSuggestions(matches, input);
  };
  nameInput.addEventListener('input', () => onType(nameInput, false));
  phoneInput.addEventListener('input', () => onType(phoneInput, true));
  document.addEventListener('click', (e) => { const box = document.getElementById('clientSuggestions'); if (box && !box.contains(e.target) && e.target !== nameInput && e.target !== phoneInput) hideSuggestions(); });
}
function showSuggestions(list, anchor) {
  let box = document.getElementById('clientSuggestions');
  if (!box) { box = document.createElement('div'); box.id = 'clientSuggestions'; box.className = 'client-suggestions'; document.querySelector('#newBookingModal .modal-card').appendChild(box); }
  if (!list.length) { hideSuggestions(); return; }
  box.innerHTML = ''; list.forEach(c => { const it = document.createElement('div'); it.className = 'suggestion-item'; it.textContent = `${c.name || 'Без имени'}${c.phone ? ' — ' + c.phone : ''}`; it.onclick = (e) => { e.stopPropagation(); document.getElementById('nbClientName').value = c.name || ''; document.getElementById('nbClientPhone').value = c.phone || ''; selectedClientId = c.id; hideSuggestions(); }; box.appendChild(it); });
  const r = anchor.getBoundingClientRect(), fr = document.querySelector('#newBookingModal .modal-card').getBoundingClientRect();
  box.style.top = (r.bottom - fr.top + 4) + 'px'; box.style.left = (r.left - fr.left) + 'px'; box.style.width = r.width + 'px'; box.style.display = 'block';
}
function hideSuggestions() { const box = document.getElementById('clientSuggestions'); if (box) box.style.display = 'none'; }

/* ---------- misc ---------- */
function showError(msg) { document.getElementById('loading').innerHTML = `<div style="font-size:40px;opacity:.5">⚠️</div><p>${esc(msg)}</p>`; }
function goBack() { if (tg?.initData) tg.close(); else location.href = '/login'; }
async function webLogout() { await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }); location.href = '/login'; }
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeSheet(); closeNewBookingModal(); if (moveMode) cancelMove(); } });
