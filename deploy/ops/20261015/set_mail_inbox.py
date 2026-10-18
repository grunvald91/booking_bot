"""Connect the owner inbox to mail.servgo.ru. Run on the server as root:
    python3 /opt/servgo-releases/20261015/set_mail_inbox.py
Asks for the mailbox login and password (input hidden), checks them against
IMAP first, then stores them in /etc/servgo/mail.env (0600) and restarts the
mail services. Nothing is printed or logged.
"""
import getpass, imaplib, os, ssl, subprocess, sys, tempfile, shutil, time
from pathlib import Path

ENV = Path('/etc/servgo/mail.env')
KEYS = ('SERVGO_MAIL_IMAP_USER', 'SERVGO_MAIL_IMAP_PASSWORD')


def check(user, password):
    with imaplib.IMAP4_SSL('mail.servgo.ru', 993, timeout=15, ssl_context=ssl.create_default_context()) as box:
        box.login(user, password)
        box.select('INBOX', readonly=True)


def main():
    user = input('Логин ящика [support@servgo.ru]: ').strip() or 'support@servgo.ru'
    password = getpass.getpass('Пароль (не отображается): ')
    if not password or any(c in password for c in '\n\r"\\$`'):
        sys.exit('Пароль пустой или содержит символы \\n " \\ $ `, которые нельзя сохранить в mail.env')
    try:
        check(user, password)
    except Exception as exc:
        sys.exit(f'Вход по IMAP не удался ({type(exc).__name__}). Ничего не изменено.')
    backup = ENV.with_name(f'mail.env.bak.{int(time.time())}')
    shutil.copy2(ENV, backup); os.chmod(backup, 0o600)
    lines = [l for l in ENV.read_text().splitlines() if not l.startswith(tuple(k + '=' for k in KEYS))]
    lines += [f'{KEYS[0]}="{user}"', f'{KEYS[1]}="{password}"']
    fd, tmp = tempfile.mkstemp(dir=ENV.parent)
    with os.fdopen(fd, 'w') as f: f.write('\n'.join(lines) + '\n')
    os.chmod(tmp, 0o600); os.replace(tmp, ENV)
    subprocess.run(['systemctl', 'restart', 'booking-web-api', 'servgo-mail-worker'], check=True)
    print(f'Готово: входящие подключены. Резервная копия прежних настроек: {backup}')


if __name__ == '__main__':
    main()
