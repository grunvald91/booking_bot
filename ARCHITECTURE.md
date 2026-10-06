# ARCHITECTURE.md — ServGo

> Status: proposed canonical architecture map. Becomes authoritative after merge to main.
> This document describes confirmed current architecture and approved direction, not speculative future implementation.

## 1. Current high-level map

~~~text
                    PostgreSQL
                  shared domain data
                         |
        +----------------+----------------+
        |                |                |
   Telegram bot      FastAPI API      Legacy Web
     aiogram           web/api          aiohttp
      bot/                |             webapp/
                          |
                     React Web UI
                    web/frontend/
~~~

Основные каналы должны работать с общей серверной domain model и общей базой данных.

## 2. Database

Основные модели определены в database/models.py.

FastAPI повторно использует эти SQLAlchemy-модели через web/api/database.py.

Подтверждённый production-oriented database stack — PostgreSQL. Локальная bot-конфигурация также допускает SQLite для отдельных development/test сценариев; SQLite не следует считать production database ServGo.

## 3. Telegram

Основная точка входа: bot/main.py.

Стек:

- Python;
- aiogram;
- Telegram Bot API;
- APScheduler.

Для FSM при доступности Redis может использоваться Redis storage. Если Redis недоступен, код допускает MemoryStorage; в этом режиме временное FSM-состояние может быть потеряно после restart процесса.

## 4. New Web stack

### Frontend

Каталог: web/frontend/

Подтверждённый стек:

- React;
- TypeScript;
- Vite;
- React Router.

Текущий frontend является Web-приложением. Полноценный PWA-слой пока не подтверждён.

### API

Каталог: web/api/

Стек:

- FastAPI;
- async SQLAlchemy;
- PostgreSQL-oriented database configuration.

Основные области API включают auth, client booking, rental, admin, subscriptions и AI-related routes.

## 5. PWA

PWA является будущим направлением.

На момент утверждения документа не подтверждены как действующие production-компоненты:

- service worker;
- Web App Manifest;
- offline cache architecture;
- push notification infrastructure.

Следовательно, текущий React frontend нельзя считать полноценной PWA.

## 6. Android

Нативный Android-клиент относится к будущему развитию.

В текущем repository booking_bot Android codebase не подтверждена и не является частью действующей архитектуры.

## 7. Legacy Web — webapp/

В проекте сохраняется старый aiohttp Web-слой.

Архитектурное направление:

1. определить, какая функциональность webapp/ реально используется;
2. переносить нужную функциональность в новый Web/FastAPI stack;
3. не добавлять новые функции в legacy Web без необходимости;
4. после переключения и проверки удалять больше не используемую legacy-реализацию;
5. конечная цель — полностью отказаться от старого Web-слоя.

Удалять webapp/ целиком до проверки фактических production-зависимостей нельзя.

## 8. Synchronization

Отдельный sync-server сейчас не подтверждён.

Согласованность между Telegram и Web достигается через общую серверную domain model и общую БД, а не через отдельную offline-first репликацию.

~~~text
Telegram ------+
               |
React/FastAPI -+--> PostgreSQL
               |
Legacy Web ----+
~~~

## 9. Bookable entity

Текущая внутренняя модель Employee может представлять:

- сотрудника;
- специалиста;
- помещение;
- кабинет;
- яхту;
- другой бронируемый объект.

На текущем этапе отдельная domain entity Resource не вводится.

Запланированное продуктовое улучшение — позволить бизнесу задавать пользовательское название этой сущности без обязательной немедленной миграции внутренней модели.

## 10. Media

Текущая реализация использует Telegram media/file identifiers для части фотографий.

Web API умеет получать Telegram media через Bot API; существуют отдельные transport settings для bot и web photo traffic.

Собственное object storage пока не является обязательным компонентом архитектуры. Оно рассматривается как дальнейшее развитие при появлении реальной эксплуатационной необходимости.

## 11. Production facts currently confirmed in repository docs/config

Подтверждено:

- repository: grunvald91/booking_bot;
- default branch: main;
- production path: /opt/booking_bot;
- systemd service booking-bot присутствует в текущих deployment instructions.

Production исторически расходился с GitHub, поэтому main нельзя считать побайтной копией production без свежей проверки.

## 12. Target source/deployment model

Целевая модель после reconciliation:

~~~text
Approved product rules/docs
          |
        GitHub
          |
       CI/tests
          |
  automatic deployment
          |
      Production
~~~

Новые production-изменения не должны появляться вручную в обход GitHub.

## 13. Production topology — verification required

Нужно провести read-only аудит production и подтвердить:

- nginx routes;
- ports;
- FastAPI runtime;
- React static deployment;
- systemd units;
- Telegram bot runtime;
- DB connection;
- health endpoints;
- production paths.

После проверки этот раздел должен быть обновлён фактическими данными.

## 14. Main sources

- bot/main.py
- bot/config.py
- database/models.py
- database/database.py
- web/api/main.py
- web/api/database.py
- web/frontend/
- web/frontend/vite.config.ts
- webapp/
- CLAUDE.md
- .github/workflows/deploy.yml
