# CLAUDE.md — ServGo

## Project
ServGo is the production booking platform in this repository.

Primary production service:
- repository: grunvald91/booking_bot
- default branch: main
- production path: /opt/booking_bot
- production systemd service: booking-bot

## Critical production rule
Production source has historically diverged from GitHub. Do NOT assume main is byte-identical to the server.

Never perform or propose a broad "copy whole repository to production" deployment unless a fresh source audit proves the relevant production paths are synchronized.

Prefer scoped changes with explicit file lists, validation, health checks, and rollback.

## Development workflow
For every requested change:
1. Read the relevant existing code before designing changes.
2. Reuse existing architecture and behavior where possible.
3. Make the smallest coherent patch.
4. Add/update focused tests.
5. Run relevant tests.
6. Run syntax/static checks applicable to changed files.
7. Inspect git diff.
8. Commit and push before optional cleanup.
9. Summarize changed files, tests, and deployment impact.

Do not edit production directly from Claude Code.

## Existing business rules
- For venue/rental pricing, reuse the existing venue_rental pricing/configuration and current pricing logic.
- Do not create a second pricing engine unless a concrete business rule cannot be represented by the existing system.
- Prepayment is transferred directly by the customer to the business owner outside ServGo.
- The customer may mark payment sent / attach proof.
- The owner manually verifies receipt.
- A booking is only treated as payment-confirmed after owner confirmation.

Do not invent product behavior or silently change these rules.

## Safety
Never commit or print:
- Telegram bot tokens
- database passwords
- SERVER_SSH_PASSWORD
- ClaudeHub/API credentials
- cookies
- OAuth tokens
- private keys
- customer personal data

Never place production secrets in issue comments or PR descriptions.

Do not run destructive database operations unless the issue explicitly requires them and a safe migration/rollback plan is part of the task.

## Production deployment
Existing GitHub Actions already contain scoped/manual production workflows using SERVER_SSH_PASSWORD.

Until source-of-truth reconciliation is complete:
- development may be automated;
- PR creation may be automated;
- production deployment remains separately gated;
- prefer existing guarded deploy scripts/workflows for changed components.

For any production-affecting change, state:
- files that must be deployed;
- service(s) that must restart;
- migration requirements;
- health checks;
- rollback path.

## Testing
Use the repository's existing tests first. Add focused regression tests for every bug fix where practical.

A task is not complete merely because code was written; preserve a committed/pushed working checkpoint.

## Mail infrastructure (owner confirmation, 2026-10-07)
The owner confirms that a self-hosted mail server was already set up. Reuse that
server through the existing SMTP module for email authentication and notifications.
Do not assume a paid delivery provider or propose rebuilding mail infrastructure.
This development workspace has no live SMTP configuration or server access; the
SMTP endpoint, TLS/DNS setup and delivery health remain to be verified on the
existing infrastructure. Never invent an endpoint or claim a successful live check.
