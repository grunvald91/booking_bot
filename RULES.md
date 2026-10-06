# RULES.md — ServGo invariants

> Status: proposed canonical invariants. Becomes authoritative after merge to main.
> Keep only rules whose violation can change or break expected product/system behavior.

## 1. One booking data model

Telegram and Web must not maintain independent sources of booking truth.

Businesses, services, employees/resources and bookings must converge on the shared server-side domain model.

## 2. Prepayment

ServGo is not the recipient of the customer payment in the current product model.

The customer transfers money directly to the business.

A customer marking payment as sent, or uploading a receipt, does not by itself confirm receipt of funds.

Prepayment becomes confirmed only after confirmation by the business.

## 3. Configurable booking interval

ServGo does not have a mandatory global 15- or 30-minute slot interval.

The interval is configurable.

The current default when no custom value is set is 30 minutes.

## 4. Consistent availability

Different ServGo interfaces must not treat the same interval as free in one channel and occupied in another.

Rules that determine whether an interval is blocked must remain consistent across channels.

## 5. Rental pricing

Existing venue_rental pricing/configuration must be reused for the same pricing problem.

Do not introduce a second independent pricing engine without an explicit architectural/product decision.

If the final price is unknown, the system must not present an incomplete calculation as final.

## 6. Bookable object model

The current internal domain model uses Employee and may represent both people and non-person bookable objects.

Introducing a parallel Resource/Room model is a domain migration and must not happen as an incidental refactor.

User-facing naming may vary by business.

## 7. Ownership and authorization

Authorization must reflect the user's actual relationship to the specific business.

Business.owner_id must not be treated as the only possible ownership mechanism because the system also supports BusinessOwner.

Changes to role or ownership semantics require checking all relevant Web and Telegram entry points.

## 8. GitHub is the path for changes

After production/GitHub reconciliation is complete, new production code changes must flow through GitHub and the deployment pipeline.

Manual production editing is not a normal development path.

## 9. Production is runtime fact

For the question “what is running right now?”, fresh production evidence takes precedence over repository assumptions.

Any divergence between production and GitHub must be surfaced and reconciled; it must not be silently normalized.

## 10. Canonical documentation is normative after approval

This first canonical documentation layer is being reconstructed from working code and production evidence.

After approval and merge:

- PRODUCT.md defines product purpose and major scenarios;
- RULES.md defines product/system invariants;
- ARCHITECTURE.md defines the intended system map.

A future accidental code change does not automatically rewrite an approved invariant. A conflict is a bug, drift, or an explicit change request.

## 11. Reproducible deployment and rollback

Production releases must be tied to a known Git commit SHA.

Target behavior:

~~~text
merge
→ deploy known SHA
→ health check
→ success
~~~

On failure:

~~~text
deploy
→ failed health check
→ restore previous known production SHA
→ health check
~~~

## 12. Destructive database operations

Destructive production DB changes require:

- understood impact;
- migration plan;
- backup/recovery strategy;
- rollback strategy;
- explicit owner approval when data-loss risk exists.

## 13. Secrets and customer data

Do not commit or expose through Issues, PRs or ordinary logs:

- bot tokens;
- API keys;
- DB passwords;
- SSH credentials;
- OAuth credentials;
- private keys;
- cookies/session secrets;
- unnecessary customer PII.

## 14. Do not invent product behavior

An AI agent or developer must not create a new business rule merely because it simplifies implementation.

When behavior is not defined and the choice materially affects users or business semantics, owner decision is required.
