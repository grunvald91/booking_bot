# AGENTS.md — ServGo

> Status: proposed canonical cross-agent instructions. Becomes authoritative after merge to main.
> CLAUDE.md remains the Claude Code-specific companion document.

## 1. Core rule

Do not guess how ServGo works.

Before changing the system, inspect the relevant current implementation, canonical documentation, tests, schemas and deployment context.

When evidence conflicts, surface the conflict instead of silently choosing the convenient source.

## 2. Source authority depends on the question

### What is running right now?

Use, in order:

1. fresh production evidence;
2. recorded deployed version/SHA;
3. current repository state;
4. documentation;
5. historical materials.

### How should the product behave?

After these docs are merged:

1. RULES.md;
2. PRODUCT.md;
3. explicit current owner decision;
4. current implementation.

If code violates an approved invariant, treat it as bug/drift or an explicit requested change. Do not rewrite the invariant automatically.

### How is the system structured?

Use:

1. fresh implementation;
2. ARCHITECTURE.md;
3. deployment/runtime configuration;
4. confirmed production audit.

### What work is current?

Use:

1. GitHub Issues;
2. ROADMAP.md;
3. explicit current owner direction.

## 3. Historical sources are context, not automatic authority

Do not treat the following as current truth without reconfirmation:

- old docs/plans/*;
- old README sections;
- old deployment instructions;
- old ROLLBACK_GUIDE.md;
- past chats;
- AI memory;
- comments describing a previous architecture.

They may explain why a decision was made, but do not prove the current state.

## 4. Before modifying anything

Inspect:

1. task/Issue;
2. git status;
3. current branch;
4. current HEAD;
5. relevant PRODUCT/RULES/ARCHITECTURE sections;
6. relevant implementation;
7. related tests;
8. database/schema impact;
9. deployment impact.

For a production-affecting change also establish:

- exact files affected;
- services affected;
- migration requirements;
- health check;
- rollback path;
- whether the affected production files are reconciled with GitHub.

## 5. Uncommitted changes

Unknown uncommitted work belongs to the user or another process until proven otherwise.

Do not destroy it.

Do not use destructive cleanup commands against unknown changes for convenience, including forceful reset/clean/restore patterns.

If a required file already has uncommitted changes:

1. inspect the existing diff;
2. understand its purpose;
3. preserve unrelated work;
4. make the requested patch only when coexistence is safe.

Do not include unrelated user changes in your commit.

If existing work conflicts with the requested product behavior, request owner decision.

## 6. Prefer the smallest coherent change

Do not perform a broad refactor merely because it looks cleaner.

Prefer the smallest coherent change that solves the task while preserving approved behavior.

## 7. What an AI agent may decide independently

Within an already approved contract, the agent may choose:

- internal helper structure;
- private function names;
- test implementation;
- safe behavior-preserving refactors;
- regression-test details;
- implementation details that do not change user/business semantics.

## 8. What requires explicit owner decision

Ask the owner before:

- changing a product invariant;
- changing a material user journey;
- changing prepayment semantics;
- changing authorization/role semantics;
- changing the meaning of stored data;
- choosing between incompatible business behaviors;
- deleting real user/business data;
- performing a destructive DB migration with data-loss risk;
- introducing a new payment flow;
- making an irreversible or difficult-to-recover change.

## 9. Verification

Writing code is not completion.

### Python/backend

Run relevant:

- tests;
- syntax/import checks;
- focused regression tests;
- runtime checks appropriate to the changed area.

### React frontend

At minimum run the repository build path:

    npm run build

Run relevant lint/type checks.

User-interface changes should be exercised in the actual affected flow when possible.

### Database

Check:

- compatibility with existing data;
- migration behavior;
- defaults;
- rollback implications.

### Production

After an approved deployment:

1. verify process/service state;
2. verify relevant health endpoint;
3. verify the changed user-facing flow when safe;
4. inspect relevant logs.

Successful file upload is not proof of successful deployment.

## 10. Git workflow

Target development path:

~~~text
Issue
→ branch
→ implementation
→ tests
→ commit
→ push
→ PR
→ review
→ merge
~~~

Target deployment path after pipeline stabilization:

~~~text
merge
→ automatic production deployment
→ health check
→ success or rollback
~~~

## 11. Production deployment

Production must not be edited directly as a normal development workflow.

After reconciliation, GitHub is the only normal path for delivering new code.

Each deployment must be tied to a known Git SHA.

The deployment system must record both:

- new SHA;
- previous production SHA.

Failed deployment must have a tested path back to the previous known production SHA.

## 12. Legacy Web

webapp/ is legacy.

Before changing it, determine whether the behavior should remain there temporarily or should move to the new Web/FastAPI stack.

Do not add new legacy dependencies without a clear reason.

Do not delete legacy code until production is verified not to depend on it.

## 13. Product naming

New product-facing naming is ServGo.

Do not introduce new BookingBot, SochiService or Sochiservice_bot branding.

Replace historical names gradually and safely rather than through a risky global rename.

## 14. Documentation maintenance

Update canonical documentation in the same PR when an approved change modifies that layer.

### Update PRODUCT.md when

- product purpose changes;
- main user types change;
- a major user scenario is added/removed;
- major product scope changes.

### Update ARCHITECTURE.md when

- a component is added/removed;
- data ownership changes;
- storage/synchronization changes;
- runtime/deployment topology materially changes.

### Update RULES.md when

an invariant changes by explicit product-owner decision.

Ordinary implementation changes do not automatically rewrite RULES.md.

### Update ROADMAP.md when

- a major direction starts;
- a major direction completes;
- a direction is cancelled;
- priorities materially change.

Small tasks belong in GitHub Issues.

### Update AGENTS.md when

- source-of-truth policy changes;
- agent permissions change;
- development/review workflow changes;
- deployment safety requirements change.

## 15. CLAUDE.md

CLAUDE.md remains the Claude Code-specific instruction file.

AGENTS.md contains cross-agent rules.

They must not silently drift into contradictory instructions. If a conflict is found, report it and resolve the documentation before relying on the conflicting rule.
