# Mailbox page fix (mail.servgo.ru → «Входящие»)

`owner_mail_ui.live.html` is the production copy (sha256 `6c4d1bd8…a76f2`).
`owner_mail_ui.html` is the fix (sha256 `18f0dd8f…e8ae9`):

- removes the stray `}` in the «Создать предложения» handler; that syntax error stopped the whole
  script, so the page never loaded the inbox and stayed on «Подключение к почтовому сервису…»;
- opens «Входящие» first; an expired session goes back to the login form;
- phone layout: bottom tab bar, one scrollable row of actions, compact counters, the opened letter
  scrolls into view. Tablet keeps the icon rail; desktop is unchanged apart from the shorter labels.

Verified in Chromium with mocked API responses at 390×844 and 1280×800: no page errors, all API
calls made, the letter opens. The old copy reproduces `Unexpected token '}'`.

Deploy: replace `/opt/booking_bot/web/api/routes/owner_mail_ui.html` (static file read on every
request, no restart). Keep a backup and check the live sha256 first.
Rollback: copy the backup back.
