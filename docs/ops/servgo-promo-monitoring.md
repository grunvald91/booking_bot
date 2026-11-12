# ServGo promo isolation and health alerts

## Actual production layout (31 October 2026)

- `promo.servgo.ru`: Nginx `/etc/nginx/sites-available/servgo-promo` passes only the promo vhost to `127.0.0.1:18080`.
- `servgo-promo-web.service`: runs `webapp.promo_standalone` separately from Telegram polling, with no dependency on `booking-bot.service` or the SOCKS relay.
- `booking-bot.service`: continues polling Telegram and serving legacy routes on `8080`; it can fail without removing promo's separate listener.
- The existing source for page templates, landing forms, SEO routes and assets is reused. No links or campaign UTM parameters were changed.
- Initial rollout uses a dedicated, verified backup of the promo Nginx config, and never edits other vhosts.

## Notifications

`servgo-health-monitor.timer` runs a dedicated oneshot monitor every 2 minutes,
independent of the booking bot process. Alert delivery uses the configured
ServGo Growth owner-notification bot (`TELEGRAM_BOT_TOKEN` and
`TELEGRAM_OWNER_CHAT_ID` from `/opt/ai_growth_os/.env`) unless
`SERVGO_MONITOR_BOT_TOKEN` / `SERVGO_MONITOR_CHAT_ID` explicitly override.
It tries direct HTTPS first; if that transport fails, SOCKS5 at
`127.0.0.1:1089` is a fallback.

Independent probes run in a bounded thread pool so a wider outage does not
consume the systemd task timeout through 36 sequential network timeouts.
Each failure is confirmed twice before the first alert. After two consecutive
successes the system sends recovery. One still-failing incident is repeated
at most every 6 hours. Large incident groups are split into Telegram-sized
batches; failed batches are not acknowledged in the state. If the state file
cannot be saved (e.g. the filesystem is full), the monitor still attempts
immediate emergency alert delivery rather than waiting for a second sample.
State persists under `/var/lib/servgo-monitor/state.json`.
No log bodies, visitor data, tokens or contact details are put in alerts.

**36 checks currently enabled:**
- 13 systemd services/timers (Nginx, BookingBot and API, promo, mail worker,
  PostgreSQL, Redis, Dovecot, Postfix, proxy/relay and backup/cert timers);
- 8 Docker containers, including Growth API, worker, Telegram and database
  and active Sushef / Elitles containers;
- 8 ServGo HTTPS domains;
- Telegram SOCKS egress;
- independent promo loopback `/_promo_health` and the legacy booking Mini App listener on `8080`;
- root filesystem utilization;
- expiry/validation of the three core HTTPS certificates.

The protected `sto.servgo.ru` login gate deliberately responds HTTP 401 to
anonymous requests; monitor interprets that one response as reachable.

## Read-only diagnosis

```bash
systemctl status servgo-promo-web.service --no-pager
systemctl status servgo-health-monitor.timer --no-pager
journalctl -u servgo-health-monitor.service -n 30 --no-pager
curl -sSI http://127.0.0.1:18080/_promo_health
curl -sSI --resolve promo.servgo.ru:443:127.0.0.1 https://promo.servgo.ru/
cd /opt/booking_bot
venv/bin/python ops/servgo_monitor.py --check
```

`--check` never sends messages or changes incident state. `--test-message`
sends exactly one owner-test message. Any new module should be added to the
monitor's explicit service/container/site inventory with a regression test.

## Rollback

The initial guarded release saved the original promo vhost in
`/opt/booking_bot/releases/promo-isolation-<UTC timestamp>/servgo-promo.nginx.orig`.
Before restoring legacy `8080`, verify that `booking-bot.service` and legacy
HTTP responses on port 8080 are healthy. Then restore the original promo-only
vhost, check `nginx -t`, reload Nginx and verify both promo and servgo.ru.
Only after successful verification stop/disable the independent promo unit.
Do not restore the vhost blindly when the bot/proxy is down.

## Coverage boundary

This monitor runs *inside the same VPS*. If the entire VPS fails, its
network is disconnected, or Telegram is unreachable through both direct
and proxy routes, **Telegram delivery is not guaranteed**. That last
failure mode needs an external watchdog with independent Telegram credentials
(for example a separate hosted GitHub Actions monitor with two repository
secrets), not merely another timer on this server. Do not claim that this
single-VPS implementation covers full-host or full-network outages.

## Merging vs applying

The production migration already ran from a guarded, now-removed one-time
GitHub workflow. The historical `scripts/deploy_servgo_promo_monitor.py`
is a **one-time bootstrap** whose drift guard intentionally prevents
blindly repeating that earlier migration after subsequent hotfixes.

Merging PR #111 into `main` publishes the reviewed source code and deploy
workflow, but **does not automatically update the installed monitor code**:
the standard webapp deployment workflow does not include `ops/**` paths.
A subsequent scoped monitor update must compare current production bytes with
an approved baseline and be verified before applying it. Do not assume this
updated batching/parallel-probe logic is live just because its CI is green.

The regular webapp deploy does restart the independent promo process after
`webapp/**` source changes, then verifies public `/`, `/beauty` and
`/robots.txt` endpoints. It continues to restart the legacy BookingBot
because that older process still serves other webapp routes.

## Verified production runs

- Isolated promo release: https://github.com/grunvald91/booking_bot/actions/runs/41237952577
- 23/23 base monitor health & protected STO correction: https://github.com/grunvald91/booking_bot/actions/runs/41238110646
- 35/35 after adding Growth containers/mail/timers: https://github.com/grunvald91/booking_bot/actions/runs/41238329338
