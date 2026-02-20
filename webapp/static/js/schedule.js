// Schedule Page JavaScript
let tg = null;
let businesses = [];
let selectedBusinessId = null;

// Schedule state
let weekOffset = 0;
let scheduleData = [];
let employees = [];
let services = [];
let clients = [];
let businessType = '';
let selectedEmployeeId = null;
let clientColorMap = {};
let colorIndex = 0;

// Time slots (8:00 - 22:00)
const TIME_SLOTS = [];
for (let h = 8; h <= 22; h++) {
    TIME_SLOTS.push(`${h.toString().padStart(2, '0')}:00`);
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Wait a bit for Telegram SDK to initialize
    setTimeout(initApp, 100);
});

async function initApp() {
    // Try to get Telegram WebApp
    tg = window.Telegram?.WebApp;

    console.log('Schedule init:', {
        hasTelegram: !!window.Telegram,
        hasWebApp: !!tg,
        hasInitData: !!tg?.initData,
        initDataLength: tg?.initData?.length || 0
    });

    // Initialize Telegram WebApp
    if (tg) {
        tg.ready();
        tg.expand();

        // Apply Telegram theme
        if (tg.colorScheme === 'dark') {
            document.body.classList.add('tg-theme');
        }
    }

    // Если нет Telegram — показываем кнопку выхода вместо кнопки назад
    if (!tg?.initData) {
        const backBtn = document.querySelector('.back-btn');
        if (backBtn) {
            backBtn.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
            backBtn.setAttribute('onclick', 'webLogout()');
            backBtn.setAttribute('title', 'Выйти');
        }
    }

    // Load businesses (authentication via X-Telegram-Init-Data header or cookie)
    await loadBusinesses();

    // Setup business select
    const businessSelect = document.getElementById('businessSelect');
    businessSelect.addEventListener('change', (e) => {
        selectedBusinessId = e.target.value;
        if (selectedBusinessId) {
            loadSchedule();
        }
    });
}

async function apiRequest(endpoint) {
    const headers = {
        'Content-Type': 'application/json'
    };

    // Add Telegram init data for authentication
    if (tg?.initData) {
        headers['X-Telegram-Init-Data'] = tg.initData;
    }
    // Без Telegram — cookie отправляется автоматически

    console.log('API Request:', endpoint, 'Has initData:', !!tg?.initData);

    const response = await fetch(endpoint, { method: 'GET', headers, credentials: 'same-origin' });
    const data = await response.json();

    if (!response.ok) {
        // Если 401 и нет Telegram — перенаправляем на логин
        if (response.status === 401 && !tg?.initData) {
            window.location.href = '/login?to=/schedule';
            return { error: 'redirect' };
        }
        console.error('API Error:', response.status, data);
        return { error: data.error || `HTTP ${response.status}` };
    }

    return data;
}

async function loadBusinesses() {
    try {
        const data = await apiRequest('/api/analytics/businesses');

        if (data.error) {
            if (data.error === 'redirect') return;
            if (data.error === 'Unauthorized') {
                showError('Не удалось авторизоваться. Войдите через /login или откройте через Telegram.');
            } else {
                showError(data.error);
            }
            return;
        }

        if (data.businesses && data.businesses.length > 0) {
            businesses = data.businesses;

            const select = document.getElementById('businessSelect');
            select.innerHTML = '<option value="">Выберите бизнес</option>';

            businesses.forEach(b => {
                const option = document.createElement('option');
                option.value = b.id;
                option.textContent = b.name;
                select.appendChild(option);
            });

            // Auto-select first business
            if (businesses.length > 0) {
                selectedBusinessId = businesses[0].id;
                select.value = selectedBusinessId;
                await loadSchedule();
            }
        } else {
            showError('Нет доступных бизнесов');
        }
    } catch (error) {
        console.error('Error loading businesses:', error);
        showError('Ошибка загрузки данных');
    }
}

async function loadSchedule() {
    if (!selectedBusinessId) return;

    try {
        // Calculate week dates
        const today = new Date();
        const dayOfWeek = today.getDay();
        const mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek; // Monday

        const weekStart = new Date(today);
        weekStart.setDate(today.getDate() + mondayOffset + (weekOffset * 7));
        weekStart.setHours(0, 0, 0, 0);

        const weekEnd = new Date(weekStart);
        weekEnd.setDate(weekStart.getDate() + 6); // Sunday

        const startDate = formatDateISO(weekStart);
        const endDate = formatDateISO(weekEnd);

        console.log('Loading schedule:', { startDate, endDate, weekOffset });

        const data = await apiRequest(`/api/analytics/schedule?business_id=${selectedBusinessId}&start_date=${startDate}&end_date=${endDate}`);

        if (data.error) {
            showError(data.error);
            return;
        }

        scheduleData = data.bookings || [];
        employees = data.employees || [];
        services = data.services || [];
        clients = data.clients || [];
        businessType = data.business_type || '';

        // Update week label
        updateWeekLabel(weekStart, weekEnd);

        // Render employee tabs
        renderTabs();

        // Render schedule table
        renderSchedule(weekStart);

        // Show main content
        document.getElementById('loading').style.display = 'none';
        document.getElementById('mainContent').style.display = 'flex';

        // Show FAB button
        document.getElementById('fabAddBooking').style.display = 'flex';

    } catch (error) {
        console.error('Error loading schedule:', error);
        showError('Ошибка загрузки расписания');
    }
}

function formatDateISO(date) {
    const year = date.getFullYear();
    const month = (date.getMonth() + 1).toString().padStart(2, '0');
    const day = date.getDate().toString().padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function updateWeekLabel(weekStart, weekEnd) {
    // weekStart and weekEnd are Date objects
    const start = weekStart instanceof Date ? weekStart : new Date(weekStart);
    const end = weekEnd instanceof Date ? weekEnd : new Date(weekEnd);

    const formatDateShort = (d) => {
        return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
    };

    const label = document.getElementById('weekLabel');

    if (weekOffset === 0) {
        label.textContent = 'Эта неделя';
    } else if (weekOffset === 1) {
        label.textContent = 'След. неделя';
    } else if (weekOffset === -1) {
        label.textContent = 'Прош. неделя';
    } else {
        label.textContent = `${formatDateShort(start)} - ${formatDateShort(end)}`;
    }
}

function navigateWeek(direction) {
    weekOffset += direction;
    loadSchedule();
}

function goToToday() {
    weekOffset = 0;
    loadSchedule();
}

function renderTabs() {
    const container = document.getElementById('employeeTabs');
    container.innerHTML = '';

    // All employees tab
    const allTab = document.createElement('button');
    allTab.className = 'tab' + (selectedEmployeeId === null ? ' active' : '');
    allTab.innerHTML = '<span class="tab-icon">👥</span>Все';
    allTab.onclick = () => selectEmployee(null);
    container.appendChild(allTab);

    // Individual employee tabs
    employees.forEach(emp => {
        const tab = document.createElement('button');
        tab.className = 'tab' + (selectedEmployeeId === emp.id ? ' active' : '');
        tab.innerHTML = `<span class="tab-icon">👤</span>${emp.name}`;
        tab.onclick = () => selectEmployee(emp.id);
        container.appendChild(tab);
    });
}

function selectEmployee(empId) {
    selectedEmployeeId = empId;
    renderTabs();
    renderSchedule();
}

function renderSchedule(weekStartParam) {
    // weekStartParam can be Date or string
    const weekStart = weekStartParam instanceof Date ? weekStartParam :
                      (weekStartParam ? new Date(weekStartParam) : getWeekStart());

    // Render header
    renderHeader(weekStart);

    // Render body
    renderBody(weekStart);
}

function getWeekStart() {
    const now = new Date();
    now.setDate(now.getDate() - now.getDay() + 1 + (weekOffset * 7));
    now.setHours(0, 0, 0, 0);
    return now;
}

function renderHeader(weekStart) {
    const thead = document.getElementById('scheduleHead');
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    const dayNames = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

    let html = '<tr><th></th>';

    for (let i = 0; i < 7; i++) {
        const day = new Date(weekStart);
        day.setDate(day.getDate() + i);

        const isToday = day.getTime() === today.getTime();

        html += `<th class="${isToday ? 'today' : ''}">
            <div class="day-name">${dayNames[i]}</div>
            <div class="day-date">${day.getDate()}</div>
        </th>`;
    }

    html += '</tr>';
    thead.innerHTML = html;
}

function renderBody(weekStart) {
    const tbody = document.getElementById('scheduleBody');

    // Filter bookings by selected employee
    let filteredBookings = scheduleData;
    if (selectedEmployeeId !== null) {
        filteredBookings = scheduleData.filter(b => b.employee_id === selectedEmployeeId);
    }

    console.log('Rendering bookings:', filteredBookings.length, 'weekStart:', weekStart);

    // Build color map for clients
    buildColorMap(filteredBookings);

    // Group bookings by day and time
    const bookingsByCell = {};

    filteredBookings.forEach(booking => {
        const bookingDate = new Date(booking.date);
        const dayIndex = getDayIndex(bookingDate, weekStart);

        // API returns 'time' field, not 'time_start'
        const timeStr = booking.time || booking.time_start;
        if (dayIndex >= 0 && dayIndex < 7 && timeStr) {
            const startHour = parseInt(timeStr.split(':')[0]);
            const key = `${dayIndex}-${startHour}`;

            if (!bookingsByCell[key]) {
                bookingsByCell[key] = [];
            }
            bookingsByCell[key].push(booking);
        }
    });

    let html = '';

    TIME_SLOTS.forEach((timeSlot) => {
        const hour = parseInt(timeSlot.split(':')[0]);

        html += '<tr>';
        html += `<td>${timeSlot}</td>`;

        for (let dayIndex = 0; dayIndex < 7; dayIndex++) {
            const key = `${dayIndex}-${hour}`;
            const cellBookings = bookingsByCell[key] || [];

            // Calculate date for this cell
            const cellDate = new Date(weekStart);
            cellDate.setDate(cellDate.getDate() + dayIndex);
            const cellDateStr = formatDateISO(cellDate);

            if (cellBookings.length === 0) {
                // Empty cell - clickable to add booking
                html += `<td class="empty-cell" onclick="openNewBookingModal('${cellDateStr}', '${timeSlot}')">
                    <div class="add-booking-hint">+</div>
                </td>`;
            } else {
                html += '<td>';

                // Отслеживаем использованные цвета в ячейке чтобы избежать повторений
                const usedColorsInCell = new Set();

                cellBookings.forEach(booking => {
                    let colorIndex = getClientColorIndex(booking.client_name || booking.client_phone);

                    // Если цвет уже использован в этой ячейке, выбираем другой
                    let attempts = 0;
                    while (usedColorsInCell.has(colorIndex) && attempts < 10) {
                        colorIndex = (colorIndex + 1) % 10;
                        attempts++;
                    }
                    usedColorsInCell.add(colorIndex);

                    const colorClass = `color-${colorIndex}`;
                    // Calculate end time from duration
                    const timeStr = booking.time || booking.time_start || '00:00';
                    const duration = booking.duration || 60;
                    const endTime = calculateEndTime(timeStr, duration);
                    const height = calculateHeightFromDuration(duration);
                    const statusClass = booking.status ? `status-${booking.status}` : '';

                    // Показываем название зала/сотрудника в режиме "Все"
                    const showEmployee = selectedEmployeeId === null && booking.employee_name;
                    const employeeLabel = showEmployee ? `<div class="booking-employee">${escapeHtml(booking.employee_name)}</div>` : '';

                    html += `<div class="booking-cell ${colorClass} ${statusClass}"
                        style="height: ${height}px;"
                        onclick="showBookingDetails(${booking.id})">
                        <div class="booking-name">${escapeHtml(booking.client_name || 'Клиент')}</div>
                        ${employeeLabel}
                        <div class="booking-service">${escapeHtml(booking.service_name || '')}</div>
                        <div class="booking-time">${timeStr} - ${endTime}</div>
                    </div>`;
                });

                html += '</td>';
            }
        }

        html += '</tr>';
    });

    tbody.innerHTML = html;
}

function getDayIndex(date, weekStart) {
    const diff = date.getTime() - weekStart.getTime();
    return Math.floor(diff / (1000 * 60 * 60 * 24));
}

function buildColorMap(bookings) {
    bookings.forEach(booking => {
        const clientKey = booking.client_name || booking.client_phone;
        if (clientKey && !clientColorMap[clientKey]) {
            clientColorMap[clientKey] = colorIndex % 10;
            colorIndex++;
        }
    });
}

function getClientColor(clientKey) {
    if (!clientKey) return 'color-0';
    const idx = clientColorMap[clientKey] ?? 0;
    return `color-${idx}`;
}

function getClientColorIndex(clientKey) {
    if (!clientKey) return 0;
    return clientColorMap[clientKey] ?? 0;
}

function calculateHeight(timeStart, timeEnd) {
    const [startH, startM] = timeStart.split(':').map(Number);
    const [endH, endM] = timeEnd.split(':').map(Number);

    const startMinutes = startH * 60 + startM;
    const endMinutes = endH * 60 + endM;
    const durationMinutes = endMinutes - startMinutes;

    // 48px per hour, so each minute is 0.8px
    return Math.max(44, (durationMinutes / 60) * 48 - 4);
}

function calculateHeightFromDuration(durationMinutes) {
    // 48px per hour
    return Math.max(44, (durationMinutes / 60) * 48 - 4);
}

function calculateEndTime(startTime, durationMinutes) {
    const [hours, minutes] = startTime.split(':').map(Number);
    const totalMinutes = hours * 60 + minutes + durationMinutes;
    const endHours = Math.floor(totalMinutes / 60) % 24;
    const endMinutes = totalMinutes % 60;
    return `${endHours.toString().padStart(2, '0')}:${endMinutes.toString().padStart(2, '0')}`;
}

function showBookingDetails(bookingId) {
    const booking = scheduleData.find(b => b.id === bookingId);
    if (!booking) return;

    const statusLabels = {
        'confirmed': 'Подтверждено',
        'completed': 'Завершено',
        'pending': 'Ожидание',
        'cancelled': 'Отменено',
        'pending_prepayment': 'Ожидает предоплату',
        'prepayment_sent': 'Оплата отправлена'
    };

    // Get time and calculate end time
    const timeStr = booking.time || booking.time_start || '00:00';
    const duration = booking.duration || 60;
    const endTime = calculateEndTime(timeStr, duration);

    const modal = document.getElementById('bookingModal');
    const content = document.getElementById('modalContent');

    content.innerHTML = `
        <div class="modal-header">
            <div class="modal-title">${escapeHtml(booking.client_name || 'Клиент')}</div>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-row">
            <div class="modal-icon">📅</div>
            <div>
                <div class="modal-label">Дата и время</div>
                <div class="modal-value">${formatDate(booking.date)}, ${timeStr} - ${endTime}</div>
            </div>
        </div>
        <div class="modal-row">
            <div class="modal-icon">💼</div>
            <div>
                <div class="modal-label">Услуга</div>
                <div class="modal-value">${escapeHtml(booking.service_name || '-')}</div>
            </div>
        </div>
        ${booking.employee_name ? `
        <div class="modal-row">
            <div class="modal-icon">👤</div>
            <div>
                <div class="modal-label">Сотрудник</div>
                <div class="modal-value">${escapeHtml(booking.employee_name)}</div>
            </div>
        </div>
        ` : ''}
        <div class="modal-row">
            <div class="modal-icon">📞</div>
            <div>
                <div class="modal-label">Телефон</div>
                <div class="modal-value">${escapeHtml(booking.client_phone || '-')}</div>
            </div>
        </div>
        ${booking.price ? `
        <div class="modal-row">
            <div class="modal-icon">💰</div>
            <div>
                <div class="modal-label">Стоимость</div>
                <div class="modal-value">${booking.price} ₽</div>
            </div>
        </div>
        ` : ''}
        <div class="modal-row">
            <div class="modal-icon">📋</div>
            <div>
                <div class="modal-label">Статус</div>
                <div class="modal-value">
                    <span class="modal-status ${booking.status || 'confirmed'}">${statusLabels[booking.status] || 'Подтверждено'}</span>
                </div>
            </div>
        </div>
        ${getStatusActions(booking)}
    `;

    modal.classList.remove('hidden');
}

function getStatusActions(booking) {
    const status = booking.status;
    let buttons = '';

    // Show different buttons based on current status
    if (status === 'pending_prepayment' || status === 'prepayment_sent') {
        buttons = `
            <div class="modal-actions">
                <button class="action-btn confirm-btn" onclick="updateBookingStatus(${booking.id}, 'confirmed')">
                    ✓ Подтвердить оплату
                </button>
                <button class="action-btn cancel-btn" onclick="updateBookingStatus(${booking.id}, 'cancelled')">
                    ✕ Отменить
                </button>
            </div>
        `;
    } else if (status === 'pending' || status === 'confirmed') {
        buttons = `
            <div class="modal-actions">
                ${status === 'pending' ? `
                <button class="action-btn confirm-btn" onclick="updateBookingStatus(${booking.id}, 'confirmed')">
                    ✓ Подтвердить
                </button>
                ` : ''}
                <button class="action-btn complete-btn" onclick="updateBookingStatus(${booking.id}, 'completed')">
                    ✓ Завершить
                </button>
                <button class="action-btn cancel-btn" onclick="updateBookingStatus(${booking.id}, 'cancelled')">
                    ✕ Отменить
                </button>
            </div>
        `;
    } else if (status === 'cancelled') {
        buttons = `
            <div class="modal-actions">
                <button class="action-btn confirm-btn" onclick="updateBookingStatus(${booking.id}, 'confirmed')">
                    ↩ Восстановить
                </button>
            </div>
        `;
    }
    // For 'completed' status, no actions needed

    return buttons;
}

async function updateBookingStatus(bookingId, newStatus) {
    try {
        const statusLabels = {
            'confirmed': 'подтвердить',
            'completed': 'завершить',
            'cancelled': 'отменить'
        };

        // Confirm action
        if (!confirm(`Вы уверены, что хотите ${statusLabels[newStatus]} эту запись?`)) {
            return;
        }

        const response = await fetch(`/api/booking/${bookingId}/status`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Telegram-Init-Data': tg?.initData || ''
            },
            body: JSON.stringify({ status: newStatus })
        });

        const data = await response.json();

        if (data.success) {
            // Close modal and reload schedule
            closeModal();
            await loadSchedule();

            // Show success message
            if (tg) {
                tg.showPopup({
                    title: 'Успешно',
                    message: `Статус записи изменен`,
                    buttons: [{ type: 'ok' }]
                });
            }
        } else {
            alert(data.error || 'Ошибка при изменении статуса');
        }
    } catch (error) {
        console.error('Error updating status:', error);
        alert('Ошибка при изменении статуса');
    }
}

function closeModal() {
    document.getElementById('bookingModal').classList.add('hidden');
}

function formatDate(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleDateString('ru-RU', {
        day: 'numeric',
        month: 'long',
        year: 'numeric'
    });
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showError(message) {
    document.getElementById('loading').innerHTML = `
        <div class="empty-icon">⚠️</div>
        <p>${message}</p>
    `;
}

function goBack() {
    if (tg?.initData) {
        tg.close();
    } else {
        window.location.href = '/login';
    }
}

async function webLogout() {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
    window.location.href = '/login';
}

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeModal();
        closeNewBookingModal();
    }
});

// ========== New Booking Modal ==========

function openNewBookingModal(dateStr, timeStr) {
    if (!selectedBusinessId) {
        alert('Сначала выберите бизнес');
        return;
    }

    const isVenue = businessType === 'venue_rental';

    // Update labels for venue rental
    document.getElementById('nbEmployeeLabel').textContent = isVenue ? 'Зал / Помещение' : 'Сотрудник';

    // Populate services dropdown
    const serviceSelect = document.getElementById('nbService');
    serviceSelect.innerHTML = '<option value="">Выберите услугу</option>';
    services.forEach(svc => {
        const priceStr = svc.price ? ` - ${svc.price} ₽` : '';
        const durationStr = svc.duration ? ` (${svc.duration} мин)` : '';
        const option = document.createElement('option');
        option.value = svc.id;
        option.textContent = `${svc.name}${durationStr}${priceStr}`;
        serviceSelect.appendChild(option);
    });

    // Filter employees when service changes
    serviceSelect.onchange = () => updateEmployeeOptions(isVenue);

    // Populate all employees initially
    updateEmployeeOptions(isVenue);

    // Pre-fill date and time if provided
    if (dateStr) {
        document.getElementById('nbDate').value = dateStr;
    } else {
        document.getElementById('nbDate').value = formatDateISO(new Date());
    }

    if (timeStr) {
        document.getElementById('nbTime').value = timeStr;
    } else {
        document.getElementById('nbTime').value = '10:00';
    }

    // Pre-select employee if filtered
    if (selectedEmployeeId) {
        document.getElementById('nbEmployee').value = selectedEmployeeId;
    }

    // Clear client fields and suggestions
    document.getElementById('nbClientName').value = '';
    document.getElementById('nbClientPhone').value = '';
    hideSuggestions();

    // Reset submit button
    const submitBtn = document.getElementById('nbSubmitBtn');
    submitBtn.disabled = false;
    submitBtn.textContent = 'Создать запись';

    // Show modal
    document.getElementById('newBookingModal').classList.remove('hidden');

    // Focus on client name
    setTimeout(() => document.getElementById('nbClientName').focus(), 100);
}

function updateEmployeeOptions(isVenue) {
    const serviceSelect = document.getElementById('nbService');
    const employeeSelect = document.getElementById('nbEmployee');
    const prevValue = employeeSelect.value;

    const anyLabel = isVenue ? 'Любой свободный зал' : 'Любой свободный';
    employeeSelect.innerHTML = `<option value="">${anyLabel}</option>`;

    const selectedServiceId = parseInt(serviceSelect.value);
    let allowedIds = null;

    if (selectedServiceId) {
        const svc = services.find(s => s.id === selectedServiceId);
        if (svc && svc.employee_ids) {
            allowedIds = svc.employee_ids;
        }
    }

    employees.forEach(emp => {
        if (allowedIds !== null && !allowedIds.includes(emp.id)) {
            return; // skip employees not allowed for this service
        }
        const option = document.createElement('option');
        option.value = emp.id;
        option.textContent = emp.name;
        employeeSelect.appendChild(option);
    });

    // Restore previous selection if still available
    if (prevValue) {
        const stillExists = [...employeeSelect.options].some(o => o.value === prevValue);
        if (stillExists) {
            employeeSelect.value = prevValue;
        }
    }

    // Pre-select if filtered tab
    if (selectedEmployeeId && !prevValue) {
        const stillExists = [...employeeSelect.options].some(o => o.value == selectedEmployeeId);
        if (stillExists) {
            employeeSelect.value = selectedEmployeeId;
        }
    }
}

function closeNewBookingModal() {
    document.getElementById('newBookingModal').classList.add('hidden');
}

async function submitNewBooking(event) {
    event.preventDefault();

    const submitBtn = document.getElementById('nbSubmitBtn');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Создание...';

    const clientName = document.getElementById('nbClientName').value.trim();
    const clientPhone = document.getElementById('nbClientPhone').value.trim();
    const serviceId = document.getElementById('nbService').value;
    const employeeId = document.getElementById('nbEmployee').value;
    const bookingDate = document.getElementById('nbDate').value;
    const bookingTime = document.getElementById('nbTime').value;

    if (!clientName || !serviceId || !bookingDate || !bookingTime) {
        alert('Заполните все обязательные поля');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Создать запись';
        return;
    }

    try {
        const postHeaders = { 'Content-Type': 'application/json' };
        if (tg?.initData) postHeaders['X-Telegram-Init-Data'] = tg.initData;

        const response = await fetch('/api/admin/booking', {
            method: 'POST',
            headers: postHeaders,
            credentials: 'same-origin',
            body: JSON.stringify({
                business_id: parseInt(selectedBusinessId),
                service_id: parseInt(serviceId),
                employee_id: employeeId ? parseInt(employeeId) : null,
                date: bookingDate,
                time: bookingTime,
                client_name: clientName,
                client_phone: clientPhone,
            })
        });

        const data = await response.json();

        if (data.success) {
            closeNewBookingModal();
            await loadSchedule();

            if (tg) {
                tg.showPopup({
                    title: 'Успешно',
                    message: 'Запись успешно создана',
                    buttons: [{ type: 'ok' }]
                });
            } else {
                alert('Запись успешно создана!');
            }
        } else {
            alert(data.error || 'Ошибка при создании записи');
            submitBtn.disabled = false;
            submitBtn.textContent = 'Создать запись';
        }
    } catch (error) {
        console.error('Error creating booking:', error);
        alert('Ошибка при создании записи');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Создать запись';
    }
}

// ========== Client Autocomplete ==========

let selectedClientId = null;

function initClientAutocomplete() {
    const nameInput = document.getElementById('nbClientName');
    const phoneInput = document.getElementById('nbClientPhone');

    nameInput.addEventListener('input', () => {
        selectedClientId = null;
        const query = nameInput.value.trim().toLowerCase();
        if (query.length < 1) {
            hideSuggestions();
            return;
        }
        const matches = clients.filter(c =>
            (c.name && c.name.toLowerCase().includes(query)) ||
            (c.phone && c.phone.includes(query))
        ).slice(0, 8);
        showSuggestions(matches, nameInput);
    });

    phoneInput.addEventListener('input', () => {
        selectedClientId = null;
        const query = phoneInput.value.trim().replace(/[\s\-\(\)]/g, '');
        if (query.length < 2) {
            hideSuggestions();
            return;
        }
        const matches = clients.filter(c =>
            (c.phone && c.phone.replace(/[\s\-\(\)]/g, '').includes(query)) ||
            (c.name && c.name.toLowerCase().includes(query.toLowerCase()))
        ).slice(0, 8);
        showSuggestions(matches, phoneInput);
    });

    // Hide suggestions on click outside
    document.addEventListener('click', (e) => {
        const sugBox = document.getElementById('clientSuggestions');
        if (sugBox && !sugBox.contains(e.target) && e.target !== nameInput && e.target !== phoneInput) {
            hideSuggestions();
        }
    });
}

function showSuggestions(matchedClients, anchorInput) {
    let sugBox = document.getElementById('clientSuggestions');
    if (!sugBox) {
        sugBox = document.createElement('div');
        sugBox.id = 'clientSuggestions';
        sugBox.className = 'client-suggestions';
        document.querySelector('.new-booking-form').appendChild(sugBox);
    }

    if (matchedClients.length === 0) {
        hideSuggestions();
        return;
    }

    sugBox.innerHTML = '';
    matchedClients.forEach(client => {
        const item = document.createElement('div');
        item.className = 'suggestion-item';
        const phonePart = client.phone ? ` — ${client.phone}` : '';
        item.textContent = `${client.name || 'Без имени'}${phonePart}`;
        item.addEventListener('click', (e) => {
            e.stopPropagation();
            selectClient(client);
        });
        sugBox.appendChild(item);
    });

    // Position near the anchor input
    const rect = anchorInput.getBoundingClientRect();
    const formRect = document.querySelector('.new-booking-form').getBoundingClientRect();
    sugBox.style.top = (rect.bottom - formRect.top + 4) + 'px';
    sugBox.style.left = (rect.left - formRect.left) + 'px';
    sugBox.style.width = rect.width + 'px';
    sugBox.style.display = 'block';
}

function hideSuggestions() {
    const sugBox = document.getElementById('clientSuggestions');
    if (sugBox) {
        sugBox.style.display = 'none';
    }
}

function selectClient(client) {
    document.getElementById('nbClientName').value = client.name || '';
    document.getElementById('nbClientPhone').value = client.phone || '';
    selectedClientId = client.id;
    hideSuggestions();
}

// Initialize autocomplete when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(initClientAutocomplete, 200);
});

// ========== Pinch-to-Zoom Functionality ==========
// Используем transform для масштабирования
let currentScale = 1;
let minScale = 0.5;
let maxScale = 2.5;
let lastDistance = 0;
let isPinching = false;

function initPinchZoom() {
    const wrapper = document.getElementById('scheduleWrapper');
    const table = document.getElementById('scheduleTable');

    if (!wrapper || !table) return;

    // Touch start - detect pinch gesture
    wrapper.addEventListener('touchstart', (e) => {
        if (e.touches.length === 2) {
            isPinching = true;
            lastDistance = getDistance(e.touches[0], e.touches[1]);
            e.preventDefault();
        }
    }, { passive: false });

    // Touch move - handle pinch zoom
    wrapper.addEventListener('touchmove', (e) => {
        if (isPinching && e.touches.length === 2) {
            e.preventDefault();

            const currentDistance = getDistance(e.touches[0], e.touches[1]);
            const delta = currentDistance - lastDistance;

            // Adjust scale based on pinch
            const scaleChange = delta * 0.005;
            currentScale = Math.min(maxScale, Math.max(minScale, currentScale + scaleChange));

            applyZoom(table);
            lastDistance = currentDistance;
        }
    }, { passive: false });

    // Touch end - stop pinching
    wrapper.addEventListener('touchend', (e) => {
        if (e.touches.length < 2) {
            isPinching = false;
        }
    });

    // Double-tap to reset zoom
    let lastTap = 0;
    wrapper.addEventListener('touchend', (e) => {
        if (e.touches.length === 0 && !isPinching) {
            const currentTime = new Date().getTime();
            const tapLength = currentTime - lastTap;

            if (tapLength < 300 && tapLength > 0) {
                // Double tap detected - reset zoom
                currentScale = 1;
                applyZoom(table);
                e.preventDefault();
            }
            lastTap = currentTime;
        }
    });

    // Mouse wheel zoom for desktop
    wrapper.addEventListener('wheel', (e) => {
        if (e.ctrlKey) {
            e.preventDefault();
            const delta = e.deltaY > 0 ? -0.1 : 0.1;
            currentScale = Math.min(maxScale, Math.max(minScale, currentScale + delta));
            applyZoom(table);
        }
    }, { passive: false });
}

function applyZoom(table) {
    // CSS zoom не ломает position:sticky (в отличие от transform:scale)
    table.style.zoom = currentScale;
}

function getDistance(touch1, touch2) {
    const dx = touch1.clientX - touch2.clientX;
    const dy = touch1.clientY - touch2.clientY;
    return Math.sqrt(dx * dx + dy * dy);
}

// Initialize pinch zoom after DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Delay to ensure elements are rendered
    setTimeout(initPinchZoom, 500);
});
