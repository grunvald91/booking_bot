# ROADMAP.md — ServGo

> Status: proposed canonical roadmap.
> This file contains confirmed current state and major directions. Small/medium execution tasks belong in GitHub Issues.

## 1. Current implemented baseline

The repository currently contains:

- Telegram booking flow;
- React Web frontend;
- FastAPI backend;
- shared SQLAlchemy domain model;
- PostgreSQL-oriented production architecture;
- service booking;
- admin schedule;
- services;
- employees/bookable objects;
- venue_rental;
- prepayment flow;
- subscriptions;
- reminders;
- analytics;
- multiple owners;
- deployment tooling;
- Claude Code integration.

These are implemented capabilities, not a blanket claim of production stability.

## 2. Current maturity

ServGo has not yet been validated through enough real business-client usage to call the entire platform field-stable.

Use:

- IMPLEMENTED;
- TESTED;
- PRODUCTION VERIFIED;
- FIELD VERIFIED.

Do not use “stable” without evidence.

## 3. Priority 1 — verify production topology

Perform a read-only production audit and document:

- nginx routes;
- ports;
- FastAPI runtime;
- React deployment;
- bot runtime;
- systemd services;
- DB;
- production paths;
- health checks.

Then update ARCHITECTURE.md with confirmed facts.

## 4. Priority 2 — GitHub ↔ production reconciliation

Compare production source with main.

For each meaningful difference determine whether:

- production contains a needed change missing from GitHub;
- GitHub contains a newer intended version;
- the difference is temporary;
- the difference is erroneous.

Completion criterion:

> future production code changes flow through GitHub rather than manual server edits.

## 5. Priority 3 — reproducible deployment and rollback

Target delivery path:

~~~text
GitHub Issue
→ AI/developer
→ branch
→ tests
→ PR
→ review
→ merge
→ automatic deployment
→ health check
→ success
~~~

Failure path:

~~~text
failed health check
→ previous production SHA
→ rollback
→ health check
~~~

Near-term technical work:

1. identify and record current production version/state;
2. define deployment scope;
3. tie deployment to Git commit SHA;
4. make health checks mandatory;
5. implement rollback to the previous deployed SHA;
6. test rollback;
7. only then enable automatic deployment after merge.

## 6. GitHub Issues as execution backlog

GitHub Issues is the intended canonical backlog for concrete tasks:

- bugs;
- features;
- refactors;
- infrastructure;
- documentation.

ROADMAP.md should not duplicate every Issue.

ROADMAP answers: where is the system going?

Issues answer: what concrete work needs to be done?

## 7. Legacy Web migration

webapp/ is legacy.

Direction:

~~~text
inspect currently used legacy behavior
→ move required behavior to new Web/FastAPI
→ switch production path
→ verify
→ remove obsolete legacy implementation
~~~

New functionality should go to the new Web/FastAPI stack unless there is a clear technical reason not to.

## 8. Configurable bookable-object naming

Implement a business-level setting that controls the user-facing name of the entity currently represented internally as Employee.

Examples:

- сотрудник;
- мастер;
- специалист;
- помещение;
- кабинет;
- яхта.

This does not require immediate migration to a new Resource table/model.

## 9. Legacy naming cleanup

Historical product names such as BookingBot, SochiService and Sochiservice_bot should gradually be replaced by ServGo.

Do not perform a high-risk global rename. Clean names safely as affected areas are changed.

## 10. Later directions

### PWA

Possible goals:

- installable Web client;
- fast access to bookings;
- push notifications.

Not an immediate priority.

### Android

Possible native client in a later phase.

Not an immediate priority.

### Own media/object storage

Reconsider Telegram-based media storage when real usage makes this operationally valuable, for example after multiple business customers are actively using the system.

## 11. Not active work without a new decision

Do not silently start:

- a separate sync-server;
- offline-first synchronization architecture;
- full Employee → Resource domain migration;
- a second rental pricing engine;
- an internal payment processor.

# REVIEW REQUIRED

No current product decision blocks this documentation layer.

The following facts still require technical verification:

## A. Production topology

Verify actual nginx, ports, processes, systemd units, FastAPI/React runtime, DB connection, health checks and production paths.

## B. Production/GitHub drift

Perform reconciliation. Escalate only differences that represent conflicting product behavior and cannot be resolved as a technical sync issue.

## C. Remaining legacy web dependencies

Inventory what is still used from webapp/ before removing or migrating anything.

## D. Automatic deployment readiness

Do not enable automatic deployment until reconciliation, deployed-SHA tracking, health checks and rollback have all been verified.

## E. Resource naming implementation details

Before implementation, decide the exact UX and storage field for the business-specific name of Employee/bookable object. The product direction itself is already approved.
