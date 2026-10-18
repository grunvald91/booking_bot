# ServGo server acceptance 2026-10-08

29 live API checks passed (exit 0), including email login/verification, booking conflicts, private receipts, prepayment review, cancellation, and session revocation. Synthetic rows cleaned up; no money transferred.

SMTP_HOST=mail.servgo.ru; /etc/hosts maps this hostname to 127.0.0.1 for local Postfix. TLS verification remains enabled; relay trust remains loopback only. Configuration backups: backups/smtp-host-fix-20261008T155850Z/env.before and hosts.before.

Local SMTP accepted the test email; Gmail rejected it with 550 5.7.26 because SPF/DKIM failed. Public TXT records for servgo.ru SPF and servgo._domainkey.servgo.ru are absent. DNS is managed by Jino; no DNS control access in this session. Required SPF TXT: v=spf1 ip4:155.212.162.47 ~all (include other authorized senders if applicable). Publish the public DKIM TXT from /etc/opendkim/keys/servgo.ru/servgo.txt. Never publish the private key. Retest Gmail acceptance after DNS publication.

Acceptance helper source: 0df7e11450e92d6c4d6e0c41cddf7015803c2297; branch fix/server-acceptance-20261008. Scoped application release: d50644f13fd99671cabeebd3c71676d47da21499, preserving server-specific extensions. GitHub Actions not invoked.
