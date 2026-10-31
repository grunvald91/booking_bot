# ServGo — проверка настоящего nginx на сервере (31.10.2026)

**Источник:** [разовый SSH-аудит GitHub Actions](https://github.com/grunvald91/booking_bot/actions/runs/41183496701), 08:10 UTC. Только чтение: без перезагрузки nginx, изменения конфигурации, секретов, БД, сервисов и деплоя.

## Что подтвердил сервер

- Nginx active; `nginx -t` и `nginx -T` успешно выполнены. Слепок текущей **файловой конфигурации** nginx SHA256: `d0973ed14aec6e5f73ad6f360d86a318a4bf8f2633fced38e7fc73f92aa34964`.
- `booking-web-api`, `booking-bot` — active; среди контейнеров обнаружен `ai-growth-os-api-1`.
- `servgo.ru` уже маршрутизирует `/api/` на `127.0.0.1:8000`. `/api/legacy/` и `/api/media/` идут на `8080`, `/dating/` — на `8081`. Есть отдельные правила `/assets/`, `/sw.js`, `/manifest.webmanifest`.
- `growth.servgo.ru:443` обслуживает `/studio` через `127.0.0.1:8091` с передачей Host и X-Forwarded-Proto; также `/public/blog/`, отдельная разведка и комментарии.
- **Нет соответствующего `/studio` или `/studio/` под `servgo.ru:443`** — PWA ещё не обслуживает Growth на своём origin.
- `mail.servgo.ru:443` существует как отдельный виртуальный хост. Отсутствие его `location` в сводке не означает отсутствия обработки внутри server-level directives.

## Обнаружена дублирующая декларация servgo.ru:443

`nginx -T` показывает **два server-блока** с `server_name servgo.ru` и `listen 443`. `nginx -t` возвращает 0, но это не подтверждает отсутствие предупреждения `conflicting server name` — stderr намеренно не выводился, чтобы не показать секреты.

**Блокер:** до переноса Growth установить, какие именно конфигурационные файлы содержат два блока, их фактический IP:port и какой блок обрабатывает запросы. Иначе можно добавить `location` в игнорируемый nginx server. Проверить предупреждения, бэкап, подготовить точечный diff действующего файла, `nginx -t`, безопасный reload и smoke test. Не перехватывать существующий BookingBot `/api/*`.

Официально: [nginx request processing](https://nginx.org/en/docs/http/request_processing.html), [server_name](https://nginx.org/en/docs/http/server_names.html).

## Действительно ли исходники на сервере синхронизированы с GitHub?

Да, **для четырёх проверенных файлов** на момент аудита. SHA256 содержимого главной ветки BookingBot (коммит `6a9cf3279386b5460fa67122233688291ab18272`) совпал побайтово с SHA256 фактических production-файлов:

| Main GitHub → production | Итог |
|---|---|
| `web/api/main.py` → `/opt/booking_bot/web/api/main.py` | Совпадает |
| `web/api/routes/owner_mail.py` → одноимённый файл | Совпадает |
| `web/api/routes/studio_sso.py` → одноимённый файл | Совпадает |
| `web/frontend/public/sw.js` → `web/frontend/dist/sw.js` | Совпадает |
| `web/frontend/dist/index.html` на сервере | Хеш получен, но нет точной сборки из GitHub для сравнения |

Это выборочная проверка, **не доказательство синхронизации всех исходников, контейнеров, nginx и runtime**. Неслитые изменения из [BookingBot #107](https://github.com/grunvald91/booking_bot/pull/107) и [Growth #184](https://github.com/grunvald91/Ai_growth_os/pull/184) в `main` и на сервер ещё не попадали.

[BookingBot deploy.yml](https://github.com/grunvald91/booking_bot/blob/main/.github/workflows/deploy.yml) переносит файлы frontend/webapp и **не обновляет /etc/nginx**; у Growth [другой механизм деплоя](https://github.com/grunvald91/Ai_growth_os/blob/main/.github/workflows/deploy-growth.yml).

## Следующие действия

1. [x] Получить живую карту nginx маршрутов, upstream портов и проверенные SHA256.
2. [ ] Уточнить конфликт двух TLS-блоков `servgo.ru`, активные имена файлов и предупреждения nginx; проверить, какой server-block действительно обслуживает запросы.
3. [ ] Сверить конфигурацию на диске с реально применённой; сделать точечный diff для действующего TLS-vhost (без вывода паролей).
4. [ ] Включить шлюз Growth **только после** выпуска безопасного SW v3 и проверки внутренних путей, Origin/CSRF, SSO/роль и обратной совместимости; реальный сервер пока не изменять.
5. [ ] Android/iOS/desktop PWA — переходы клиент → admin → Growth → Mail → назад, единый light/dark/system и правильный logout; затем production rollout с rollback.

**Итог:** GitHub-код выборочно синхронизирован, но nginx управляется отдельно и сейчас не реализует основное требование «единый origin для Growth».