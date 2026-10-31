# ServGo — интеграционная ревизия и условия выпуска единого PWA

Состояние на 31.10.2026. **Интеграционная ветка, не production.**
Сводный PR BookingBot: [#107](https://github.com/grunvald91/booking_bot/pull/107).
Сводный PR Growth OS: [#184](https://github.com/grunvald91/Ai_growth_os/pull/184).

## Что вошло в проверяемую сборку

| Область | Исходный PR | Интеграционная версия |
|---|---|---|
| Безопасный PWA cache/offline | [#102](https://github.com/grunvald91/booking_bot/pull/102) | Перенесено в #107; SW v3, no-cache приватных навигаций |
| UI ServGo Air и Light/Dark/System | [#103](https://github.com/grunvald91/booking_bot/pull/103) | Включён React и Mail UI |
| Growth one-origin SSO | [#104](https://github.com/grunvald91/booking_bot/pull/104) | Флаг выключен, строгая проверка ticket URL |
| Mail PWA | [#105](https://github.com/grunvald91/booking_bot/pull/105) | Флаг выключен, `mail_owner`, path-scoped cookie |
| Growth theme + same-origin CSRF | [#182](https://github.com/grunvald91/Ai_growth_os/pull/182), [#183](https://github.com/grunvald91/Ai_growth_os/pull/183) | Комбинация #184, флаг выключен |

Изменения исходных PR собраны вручную в review-ветках из-за конфликта файла CI и зависимости #105 от #103.
Сводный CI проверяет **совместное** выполнение тестов SW, темы, Mail, SSO, nginx и сборки React.

## Выпуск блокируется до выполнения этих условий

### P0 — безопасность и правильный порядок

- [x] Все три feature flags выключены по умолчанию: `SERVGO_GROWTH_GATEWAY_ENABLED`, `STUDIO_SERVGO_GATEWAY_ENABLED`, `SERVGO_MAIL_GATEWAY_ENABLED`.
- [x] В SW v3 HTML-навигации всегда network-only. Новый offline не содержит данных аккаунта.
- [x] Mail `GET /api/logout` очищает cookie с правильным `Path=/api/owner-mail` на canonical origin, и `Path=/` на legacy host. Регрессионный тест добавлен.
- [x] Mail не выдаёт `mail_owner` другим бизнес-пользователям; SSO ticket одноразовый, привязан к origin.
- [x] Growth принимает POST второго origin только при флаге и реальном HTTPS Host `servgo.ru`.
- [x] **Провести live-аудит действующего production nginx:** после сохранённого backup и удаления дубля остаётся один `servgo.ru:443`; `nginx -t` успешен, предупреждений 0, upstream BookingBot `/api` → `127.0.0.1:8000`, Growth legacy → `127.0.0.1:8091`. Подтверждено [независимым SSH-аудитом после исправления, attempt 2](https://github.com/grunvald91/booking_bot/actions/runs/41183811915).
- [ ] **Проверить будущую конфигурацию gateway в реальном TLS-vhost:** `/studio` и `/workspace/growth` пока не активированы на `servgo.ru`. До включения сверить candidate nginx include с оставшимся блоком, сертификатом, proxy headers, API routes и резервной копией; проверить SSO на staging.
- [ ] **Проверить точечный include** `deploy/nginx/servgo-growth-gateway.inc.example` именно в контексте действующего TLS server. `nginx -t` в CI проверяет только изолированный шаблон.
- [ ] **Сохранить `growth.servgo.ru` без срока отключения**, даже после появления `servgo.ru/studio`: никаких принудительных редиректов/смены URL, прежний вход, отдельная сессия, bookmarks, deep links к проектам/задачам, GET/POST/CSRF, роль/tenant isolation и данные должны оставаться доступными. Это release-blocking требование до отдельного решения владельца.
- [ ] Сохранить безопасный доступ к `mail.servgo.ru` на время миграции; изменения Mail не должны нарушить старую почтовую ссылку.
- [ ] **Двухдоменный regression E2E до и после gateway rollout**: проверить `growth.servgo.ru/studio` и вложенные пути как с активной legacy-сессией, так и после новой авторизации; параллельно проверить новый `servgo.ru/studio`, отсутствие cross-host CSRF и отсутствие redirect со старого домена.
- [ ] Выполнить staging E2E с валидным входом и разными ролями: 401/403, чужая компания, logout, CSRF, replay, referer, cookies и no-store.
- [ ] Проверить точность SSO-разрешений и сроков жизни билетов на реальной БД/бекенде (не в CI с фейковыми пользователями).

### P0 — автоматический деплой BookingBot при merge

**Не сливать #107 в `main` до подготовки выпуска.** В [`.github/workflows/deploy.yml`](https://github.com/grunvald91/booking_bot/blob/main/.github/workflows/deploy.yml) задан `on.push.branches: main` + `web/frontend/**`; следовательно, merge #107 запускает автоматическую загрузку frontend на production **до** отдельного развёртывания API и проверки nginx. Для этого релиза требуется заранее согласованный двухрепозиторный rollout и откат.

Growth OS [`deploy-growth.yml`](https://github.com/grunvald91/Ai_growth_os/blob/main/.github/workflows/deploy-growth.yml) выполняется вручную с отдельными gate.

### P1 — визуальная и функциональная приёмка

- [ ] Android Chrome: установленная одна ServGo PWA открывает клиент → admin → Growth → Mail → обратно **в одном standalone-окне**.
- [ ] iOS Safari и desktop PWA: проверить link capture, различия OS.
- [ ] Light/Dark/System: один выбор отображается без white flash во всех четырёх рабочих областях.
- [ ] Референс ServGo Air на светлой теме: главный клиентский путь, карточка заведения, выбор услуги должны остаться визуально близкими к исходным скриншотам.
- [ ] Growth Home остаётся пустой до команды; исправлены отдельные визуальные проблемы на экране ИИ-команды/CSP и переполнение 320px.
- [ ] Переходы refresh, back/forward, deep links, режим offline, уведомления и возвращение из почты не открывают лишнюю вкладку браузера.
- [ ] Mail: поиск компании, адресатов, черновики, письма и кампании работают, но массовая реальная рассылка **не используется** для тестов.
- [ ] Проверка функционального паритета 61 сценария и подтверждённых ролей.

## Точка продолжения 31.10.2026

Независимый повторный аудит nginx завершён, поэтому исправление дубля повторять **не нужно**. Следующий невыполненный шаг — отдельно выпустить SW v3 после проверки [PR #102](https://github.com/grunvald91/booking_bot/pull/102), не включая gateway. Контрольная последовательность и ограничения обновлены в [живом плане](unified-pwa-implementation-plan.md). Никакого merge в main/переключения production в рамках этого обновления документации.

## Операторский порядок staged release (не выполнен)

1. Подтвердить релизный план с rollback и завершить визуальное ревью.
2. Развернуть и проверить SW v3 в BookingBot **до** проксирования приватных страниц.
3. Подготовить nginx vhost, выполнить `nginx -t`, включить только узкие пути Growth, проверить upstream; не трогать BookingBot `/api`.
4. Развернуть Growth OS с отключённым флагом gateway; выполнить smoke tests legacy сайта и API.
5. Включить `STUDIO_SERVGO_GATEWAY_ENABLED` на Growth; проверить same-origin POST и старую сессию.
6. Развернуть Mail/BookingBot API с отключённым флагом; проверить старый mail.
7. Включить `SERVGO_MAIL_GATEWAY_ENABLED` и проверить one-time email ticket, owner role и cookie.
8. Только последним включить `SERVGO_GROWTH_GATEWAY_ENABLED` в BookingBot; проверить live SSO и PWA навигацию.
9. Выполнить Android/iOS/desktop E2E. При ошибках — сначала выключить **issuer flags** в BookingBot, затем после истечения/завершения новых сессий откатить gateway и nginx.

Текущий git-статус: **новые флаги выключены; main и production не переключены**. Проверки CI не эквивалентны тесту установленного приложения на реальном сервере.
