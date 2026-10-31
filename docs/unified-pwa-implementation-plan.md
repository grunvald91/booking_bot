# ServGo — план реализации единого дизайна и PWA

**Дата:** 31.10.2026. **Статус на 08:36 UTC:** интеграционные PR [BookingBot #107](https://github.com/grunvald91/booking_bot/pull/107) и [Growth #184](https://github.com/grunvald91/Ai_growth_os/pull/184) подготовлены и прошли CI, оба остаются draft; единый PWA **не включён** в production.
**Продукт:** одно устанавливаемое ServGo на https://servgo.ru/.
**Визуальный эталон:** предоставленные пользователем экраны клиентского пути (каталог, заведение, услуги) и [ServGo Air](../web/frontend/src/styles/design-system.css).

Источники: [manifest](../web/frontend/public/manifest.webmanifest), [service worker](../web/frontend/public/sw.js), [аудит v4](https://github.com/grunvald91/Ai_growth_os/blob/audit/growth-v4-parity-20261031/docs/design/GROWTH_V4_REAUDIT_20261031.md), [матрица функций](https://github.com/grunvald91/Ai_growth_os/blob/main/docs/design/SERVGO_FUNCTION_MATRIX.md), [архитектурный план](https://github.com/grunvald91/Ai_growth_os/blob/audit/growth-v4-parity-20261031/docs/design/SERVGO_UNIFIED_DESIGN_PWA_PLAN.md).

## Непереговорные требования

- Одна палитра и компоненты **ServGo Air** для клиентского пути, админки, Growth и Mail. Growth сохраняет полупустую главную, где голосовая строка — главное действие.
- **Один manifest и один service worker** на `servgo.ru` со scope `/`. Backend-процессы можно оставить независимыми; их UI должны быть доступны через один origin.
- Одна настройка `light | dark | system` с серверным предпочтением для пользователя и локальной настройкой до авторизации. Никаких миганий белой темы при переходах.
- Общая оболочка **не** открывает новые права: посетитель, мастер, бизнес-владелец, оператор Growth и платформенный владелец Mail сохраняют свои серверные роли.
- Сохранить операции из [матрицы 61 функции](https://github.com/grunvald91/Ai_growth_os/blob/main/docs/design/SERVGO_FUNCTION_MATRIX.md) и 19 команд диспетчера. UI «Рисованное видео» переименовать в «Простое видео», внутреннее API `whiteboard` оставить.
- Не включать массовые рассылки/публикации в тестах. Все действия с платежами, письмами и публикациями — с подтверждением и проверкой роли.

## Дорожная карта и критерии готовности

| Этап | Работы | Где | Приёмка | Текущий статус |
|---|---|---|---|---|
| **0. Инвентаризация** | 382 маршрута, 61 функция, hostnames, CSS, PWA, CSP, роли/SSO, конфликтующие пути | Оба репо | Аудит + план, отдельная проверка фактического nginx | Код проверен, production nginx ещё не подтверждён |
| **1. Защита SW** | Запрет кеширования навигации, приватных данных и API; нейтральный offline; контроль внешних push-ссылок | BookingBot | Регрессионные тесты, обновление кеша v2 → v3, push сохранён | **Реализуется в первом PR, CI ещё требуется** |
| **2. Design tokens** | Общее семантическое ядро ServGo Air, экспорт CSS/JSON для BookingBot, Growth и Mail, единые шапки, кнопки, списки, формы | Оба | Сравнение экранов с эталоном на ПК и телефоне, light/dark | Следующий |
| **3. Единая тема** | `servgo-theme` = light/dark/system, миграция `schedTheme` и `servgo-desktop-theme`, user preference в серверном профиле | Оба | Клиент → админ → Growth → Mail → обратно: тема не меняется; перезапуск PWA | Не начат |
| **4. Same-origin gateway** | UI/API адреса под `servgo.ru`, URL-prefix, reverse proxy, assets, cookie scope, deep links, CSP и CSRF | Оба + nginx | Внутренние переходы остаются в установленном PWA, обычные reload работают | Не начат |
| **5. Авторизация и SSO** | Адаптация входа Growth и mail_owner к единому адресу, one-time tickets и серверные роли | Оба | 401/403, доступ к чужой компании, logout, anti-CSRF, нет расширения прав | Не начат |
| **6. Growth v4** | Завершение UI по ServGo Air, убрать CSP-проблему ИИ-команды и overflow 320px, подключить SEO/кампании/почту | Ai_growth_os | Все поддерживаемые функции доступны в новой оболочке, главная пустая до команды | Не начат |
| **7. Mail** | Email поиск, база, рассылки, inbox/outbox, отписки, тема, адаптив | booking_bot | Mail живёт в одном PWA, запрет доступа business-owner, тестовые отправки — только mock | Не начат |
| **8. E2E и поэтапный запуск** | Playwright + физический Android, iOS Safari, desktop, offline, push, цветовая тема, глубокие ссылки, откат | Оба | Установка одного ServGo, все внутренние переходы в одном PWA | Не начат |

## План отдельных PR

1. **PR-1 (уже начат)** — безопасный SW v3, `offline.html`, 6 регрессионных тестов и CI. Не менять URL/nginx/auth.
2. **PR-2** — канонические токены ServGo Air и единый `servgo-theme` в BookingBot; клиентская запись и админка используют одну настройку.
3. **PR-3** — экспорт токенов в Growth и Mail, безопасная настройка CSP без ослабления безопасности, дизайн мобильного/ПК.
4. **PR-4** — gateway маршрутизации, только после реальной ревизии nginx и составления таблицы конфликтов с `/api` и `/studio`.
5. **PR-5** — миграция Mail/Growth SSO, серверные права, test-only gateway, deep-link/Origin/CSRF тесты.
6. **PR-6** — постепенное переключение UI ссылок на same-origin и перенос всех функций; старые поддомены сохраняются на переходный период.
7. **PR-7** — PWA E2E матрица и выпускаемый флаг; затем отдельный production deploy с rollback.

## Целевые внешние URL (ещё НЕ существуют как готовые UI)

| Раздел | Внешний путь | Источник |
|---|---|---|
| Клиентский путь | `/`, `/business/:id`, `/book/:id`, `/my` | BookingBot React |
| Админка | `/admin/*` | BookingBot React |
| Growth | `/workspace/growth/*` | Growth OS через same-origin gateway |
| Mail | `/workspace/mail/*` | ServGo Mail через same-origin gateway |
| Growth API | `/api/growth/*` | API gateway / проверка ролей |
| Mail API | `/api/mail/*` | API gateway / mail_owner |

**Нельзя просто проксировать HTML на подмаршрут:** Growth содержит абсолютные `/studio/*`/`/products/*`, а Mail использует `/api/*`, `/claim`, отдельную cookie и `Origin == https://mail.servgo.ru`. Прежде нужны адаптеры URL, assets, redirect, CSRF и SSO. Внешняя ссылка на другой origin не гарантирует сохранение standalone PWA; экспериментальные scope_extensions не являются основным решением.

## Блокирующие требования безопасности

- **CacheStorage**: только публичная статика. Ни письма, ни приватные HTML, ни HTTP-ответы API, ни вложения/подписанные URL туда не попадают. Offline для любой приватной страницы показывает только нейтральный экран.
- **Legacy SW**: удалить cache `servgo-pwa-v2`, не затронуть чужие cache namespace и существующую push подписку.
- **Mail**: сохранить `mail_owner` только платформенному владельцу; не делать cookie с `Domain=.servgo.ru` для упрощения входа. Требуются one-time ticket с TTL/audience, HttpOnly Secure host-only cookie и анти-CSRF.
- **Growth**: сохранить tenant-scope, запрет доступа к чужой компании, текущую защиту POST/PUT и строгий CSP ИИ-команды.
- **Logout**: без возможности прочитать последнюю чужую страницу из service worker/history после выхода.
- **PWA**: нативные ссылки только через same-origin. Поддержку открытия установленного PWA из внешних мессенджеров отдельно проверять на разных ОС — она не гарантирована для всех браузеров.

## Обязательная тестовая матрица

1. Установить **одно ServGo** на Android; клиент → админ → Growth → Mail → назад; все внутренние страницы в standalone.
2. Повторить на iOS Safari и десктопном Chromium с учётом особенностей этих платформ.
3. Включить Dark на клиентском экране, перейти через все разделы, закрыть и открыть PWA, проверить сохранение Dark. Повторить Light и System.
4. Без роли `mail_owner` любой бизнес-пользователь получает 403, а не переписку и не offline-копию страницы.
5. Отключить интернет во время `/workspace/mail` и `/workspace/growth` — никакого приватного кеша, только нейтральный offline.
6. Deep link/reload для каждого подмаршрута, включая вложенные страницы. Проверить обратную прокси, POST Origin, CSP, JS assets и прокрутку.
7. Push-событие открывает разрешённый same-origin путь, требует повторной авторизации при истёкшей сессии.
8. Все 61 функции отмечены как «перенесено/подключено/осталось старое»; на 320px без overflow; видео в UI — «Простое видео».

## Точка продолжения — 31 октября 2026, 08:36 UTC

### Проверенные результаты
- Аудит реального nginx проведён: текущие пути и upstream определены, Growth — `127.0.0.1:8091`, BookingBot `/api/` — `127.0.0.1:8000`. Выборочно проверено соответствие 4 файлов GitHub main и сервера — это не полная синхронизация всего ПО.
- Дубликат TLS-конфигурации `webapp.bak_auth3_` выведен из `sites-enabled` с сохранением копии; `nginx -t` успешен, предупреждения о дублирующихся `server_name` снизились с 8 до 0; 6 HTTP-статусов во время исправления не изменились.
- **Независимый повторный SSH-аудит после reload успешен:** [run #41183811915, attempt 2](https://github.com/grunvald91/booking_bot/actions/runs/41183811915). В активном `servgo.ru:443` остался один файл `/etc/nginx/sites-enabled/webapp`; существующая маршрутизация и выбранные SHA256 не изменились. Этот аудит был read-only и **не повторял HTTP-smoke**.
- Объединённый CI: [BookingBot success](https://github.com/grunvald91/booking_bot/actions/runs/41182785554), [Growth success](https://github.com/grunvald91/Ai_growth_os/actions/runs/41182603139). CI проверяет программные контракты, а не установленную PWA на реальном телефоне.
- Области кода в review: SW v3, тема ServGo Air/Light/Dark/System, безопасный same-origin Growth SSO, Mail workspace для `mail_owner`, origin/CSRF и тестовый nginx include. **Флаги шлюзов выключены по умолчанию.** Код PR ещё не в main/production.

### Следующий этап — выпуск безопасного SW v3, прежде чем включать прокси
1. Проверить отдельный PR [#102](https://github.com/grunvald91/booking_bot/pull/102), его результат CI, влияние перехода v2 → v3 и план резервного восстановления. **Не объединять #107 целиком ради этого этапа:** [deploy.yml](https://github.com/grunvald91/booking_bot/blob/main/.github/workflows/deploy.yml) автоматически отправляет изменённый frontend после push в main.
2. Подготовить отдельный release только SW v3 с `offline.html` и нужными публичными ресурсами; до него сохранить контрольный SHA/снимок текущего `sw.js` и проверить фактический ответ CDN/nginx. Не менять сейчас `/studio`, Mail, флаги SSO и cookies.
3. На тестовом устройстве проверить обновление ранее установленной PWA, удаление прежнего cache v2, offline-переходы, push notifications, восстановление сети и запись клиента. При сбое — откат статических ресурсов по подготовленному плану.
4. После подтверждённого SW приступить к **read-only сверке предложенного nginx include с оставшимся действующим TLS-vhost** и staging-тестам Growth с флагами выключенными.
5. Затем завершить Mail/Growth gateway, полную визуальную ревизию тем и E2E (включая Android/iOS и 61 сценарий) до разрешения production rollout.

### Незакрытые ограничения
- `https://servgo.ru/studio` на production **пока не подключён**.
- Gateway-флаги и новая canonical Mail-навигация **не включены**.
- Не подтверждены пользовательские сценарии PWA на Android/iOS, контраст/верстка всех экранов, SSO с реальными ролями и действие голосового интерфейса через новый origin.
- Релиз требует отдельной проверки и согласованного отката; отсутствие nginx warnings не доказывает готовность всей платформы.

## Первый реализуемый срез

В PR-1 изменены: `web/frontend/public/sw.js`, `web/frontend/public/offline.html`, `web/frontend/tests/sw-security.test.mjs` и `.github/workflows/pwa-ci.yml`.

**Эти изменения НЕ объединяют поддомены и НЕ выпускают новый дизайн.** Это необходимая техническая защита до объединения. После прохождения CI следующим шагом будет тема и токены, не сразу рискованная смена прокси. Deploy и merge выполняются только после ревью.
