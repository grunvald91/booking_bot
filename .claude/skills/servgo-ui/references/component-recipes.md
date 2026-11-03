# Component recipes — grounded in the current BookingBot client flow

These are **reference points**, not a new CSS library. Inspect the source at the current commit before using. Prefer existing shared classes and semantic tokens over copying literal values.

Canonical files:
- `web/frontend/src/pages/client/booking-flow.css`
- `web/frontend/src/styles/design-system.css`
- `docs/brand/tokens.json`

## New screen: build a real interaction before polishing

1. Define the job-to-be-done in one sentence and the primary user action.
2. List available data, loading/empty/error and permission-denied states; preserve actual route and business context.
3. Make a mobile layout with **context above, content/work area, action bar below**. Avoid large headers that force the actionable content below the fold.
4. Use existing `ds-*` components/tokens for an admin/studio view. Recreate a booking-style step only when the task is genuinely sequential.
5. Select the correct native component: list row for a choice, sheet for details, table or timeline for dense schedules, input for edits, and meaningful charts for analytics. Don't put every row in a card.
6. Give each control its own state and real handler (disabled, active, loading, error); wire navigation to known routes and preserve back history.
7. If the user requests exploration, compare 2 compact compositions in words or sketches, choose based on the task, then implement and visually verify the chosen one. Don't replace functioning screens with illustration-only demos.

## Verified primitives from current CSS

| Component or rule | Source selector | Existing geometry / behavior |
| --- | --- | --- |
| Client screen shell | `.bf-device`, `.bf-screen` | Mobile-first column; client shell currently max 460px by default; verify desktop overrides at >=1024px before editing |
| Client step headline | `.bf-h2` | `clamp(22px, 6vw, 26px)`, weight 480, tight tracking; do **not** apply indiscriminately to dashboard headings |
| Option row | `.bf-option` | Borderless, 56px minimum row, subtle selected radial tint and icon/label/metatext hierarchy |
| Client bottom actions | `.bf-bottombar`, `.bf-back`, `.bf-primary` | Back next to primary action, safe-area bottom; primary 112deg blue gradient and 12px radius in client flow |
| Bottom sheet | `.bf-sheet` | 24px upper radii, 82dvh max, scrolling and safe-area bottom; admin sheet uses `.ds-sheet` and its own tokens |
| Admin bottom navigation | `.ds-bottomnav`, `.ds-bn` | Grid with aligned icons/labels, active underline attached to each individual tab; safe-area padding |
| Admin or Studio color | `--s-bg`, `--s-surface-2`, `--s-surface-3`, `--s-text`, `--s-accent` | Theme-dependent semantic variables, not fixed inline light-theme colors |

## The tapered animated underline: avoid the recurrent regression

There are **two related existing implementations**, not a single interchangeable CSS rule:
- Client `.bf-choice.is-complete::after, .bf-option.selected::after, .bf-time.selected::after`: normally 52% width, 2px high, 3.8s flowing gradient, polygon clipping **and** fading mask. Time selection is **76%** width.
- Admin `.choice-accent::after`: left/right 17%, height 2.4px, 3.7s, polygon clipping. `.ds-bn::after` uses left/right 22%, 2px, the same clipping profile and gradient, shown **only on `.ds-bn.active`**.
- Exact polygons and gradients live in the current stylesheets. Do not hand-wave them into `border-bottom`, `box-shadow`, rounded pills or a constant-width solid bar.
- Keep the underline aligned with the **active control**, not the whole bottom dock. For Studio, use a shared active-state style that matches these real implementations without pulling in the entire BookingBot stylesheet.
- When reduced motion is requested, stop the perpetual gradient animation.

## Visual quality gates for generation and review

- Inspect **the real rendered UI** at 360, 390, 430px phone widths, a short phone viewport, and desktop >=1024px; include dark mode for admin/studio. Current BookingBot also has an admin breakpoint at 900px, so include it for navigation changes.
- Check the full path: initial view, selection, keyboard open, long list, empty/loading/error, bottom sheet, back/close, completed action, company switch and navigation return where relevant.
- Test 320–360px too when a control label is long; visually confirm no overflows or controls covered by a sticky footer.
- Accessibility: aim for WCAG AA contrast for essential text and controls; the brand book itself documents low-contrast `bf-muted` and `s-muted-2` cases. **Do not reproduce known insufficient contrast for critical content** just to match a screenshot. Use visible focus, semantic labels, readable text and sufficiently large touch targets.
- Use screenshots with synthetic data only. If a real browser or screenshot baseline is not available, state **visual QA not verified**, not a pass.

## Deliverable for an implementation task

Return a concise change report with (1) original screen and exact source files, (2) reused design tokens/classes, (3) new behavior and real handlers, (4) screenshots and interaction paths actually checked, (5) automated tests, (6) known limitations and whether deployment was performed. Never mark a screen visually verified from static code review alone.
