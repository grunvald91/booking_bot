"""One-time post-HELO deliverability test. No OTP or account changes."""
from scripts import mnebyvpn_mail_preflight as check

def main():
    remote=check.REMOTE_CODE
    original="/var/tmp/mnebyvpn-mail-preflight-20261107"
    if original not in remote:
        raise RuntimeError("Unknown mail preflight marker")
    remote=remote.replace(original,"/var/tmp/mnebyvpn-helo-verified-20261107")
    remote=remote.replace("MNEBYVPN - SMTP verification 2026-11-07",
        "MNEBYVPN - контроль почтовых уведомлений")
    remote=remote.replace("MNEBYVPN SMTP test. No login code or VPN subscription is attached.",
        "Контроль доставки писем MNEBYVPN после настройки почтового сервера. Код входа не создавался.")
    check.REMOTE_CODE=remote
    check.main()

if __name__=="__main__":
    main()
