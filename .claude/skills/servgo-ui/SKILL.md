---
name: servgo-ui
description: "Design, implement, review or fix ServGo web UI using the real BookingBot customer booking flow as the visual and interaction reference. Use for BookingBot, Growth Studio, Mail, SEO factory, Shifts, responsive layout, colors, typography, navigation, selected underline, or screenshot-driven UI bug fixes."
---

# ServGo UI — customer booking flow is the reference

This is a **working engineering skill**, not a request to generate a static mockup. Produce working UI that respects current routing, authentication, business logic and accessibility. For visual choices, start from the **actual BookingBot customer flow**, not generic dashboards, component libraries or Stageshow demo aesthetics.

## Source of truth (read before writing UI)

1. `docs/brand/servgo-air.md`: product design principles, wording, accessibility and intended customer journey.
2. `docs/brand/tokens.json`: semantic tokens, dimensions, typography, themes, spacing and radii.
3. `web/frontend/src/pages/client/booking-flow.css`: **real customer booking UI**. Check current styles for structure, selected states, booking footer, dialogs, mobile/desktop variants and reduced motion.
4. `web/frontend/src/styles/design-system.css`: existing reusable admin components, `.ds-bottomnav`, `.ds-bn`, `.choice-accent`, `.ds-sheet`, theme variables.
5. Component and route implementation for the **specific screen** being modified; inspect its markup, transitions, handlers and related tests before editing.
6. Other ServGo modules: `grunvald91/Ai_growth_os/app/api/assets/servgo-air-tokens.css` and `growth-servgo-air.css` are consumers/adapters, **not an independent palette**. Compare to BookingBot before changing them.

If brand-book prose and the current booking UI diverge, identify the discrepancy rather than silently claiming they match. For a new look, request/record a deliberate design decision and update the brand book and consumers together. Do not paste the 86kB customer CSS into Studio.

## Visual grammar: what MUST remain recognizable

- **Airy, sparse interface**: white/light background, extremely soft blue surfaces, clear hierarchy, generous breathing room without wasting the phone viewport. No decorative gray frames, card borders, persistent separators or excessive shadows. Use semantic `--s-*`, `--bf-*`, `--r-*`, `--sh-*` variables and existing component classes.
- **Onest throughout**, correct weight, line-height and slight negative letter spacing; visually consistent headings, labels and navigation. Tabular numbers for money, times and metrics. Use existing logo assets, with appropriate contrast for light/dark themes; do not invent a logo or recolor the brand mark.
- **Exactly one primary blue action per step/context** where feasible; neutral choices use softly tinted surfaces. Semantic success/warning/error colors convey meaning with text, never color alone.
- **Active selection line is signature, not decoration.** It is a short blue-to-cyan flowing underline tapering at both ends, visible **only on the active/selected option**. See existing `.bf-choice.is-complete::after`, `.bf-option.selected::after`, `.bf-time.selected::after` and `.choice-accent::after` / `.ds-bn.active::after`. Reuse or faithfully adapt those actual implementations, including the correct existing clip geometry (and the client-only fading mask where applicable) plus `prefers-reduced-motion`. A solid rectangle/rounded pill/straight border is not the same effect. Keep the line aligned under the correct active navigation item.
- **Mobile first**: information and context above; actions, main CTA and back button at the bottom in thumb reach. Use a bottom sheet for details. A scrollable list must not hide action buttons. Account for `env(safe-area-inset-bottom)`, keyboard, very short screens, fixed bars and scroll position. All desktop features must be reachable on mobile.
- **Adapt, do not imitate literally**: booking has steps, calendars and simple options; Studio/Mail/SEO have more complex workflows. Keep their information architecture and functional density appropriate while using the *same* color, type, spacing, component geometry, navigation treatment and motion language.
- **Theme rule**: booking flow is deliberately light; administration and Growth Studio support light/dark. Dark theme is not an inverted screenshot: check text, icons, logo, surfaces and controls against real dark tokens.
- **Copywriting**: Russian, concise, on «вы». Controls describe their action; empty/loading/error states state the next step. Avoid unexplained jargon, meaningless labels, emoji as icons and clipped/concatenated words.

## Generation mode — make new interfaces, not only audit old ones

When creating a new element or page, start by specifying its primary user goal, the real content and the exact action it should perform. Choose the smallest suitable visual pattern from the live booking flow (option list, contextual scene, footer action, bottom sheet, segmented navigation), then compose with semantic tokens and the current app's own shared components. **Do not automatically wrap each element in a bordered card**.

- Draw or describe two compact layout approaches only when an exploratory design request benefits from alternatives; otherwise build the best-fitting implementation directly.
- Preserve the booking flow's visual hierarchy but adapt to the feature: charts for analytics, tables for bulk data, composers for creation, and timelines for scheduling. The reference is a *design language*, not a one-size-fits-all page layout.
- Implement all user states and real interactions. A visually attractive static demo is not a finished product.
- For concrete, code-grounded patterns read [component recipes](references/component-recipes.md) before creating a new screen, navigation item, option row, sheet or primary action.

## Workflow for EVERY design or redesign request

1. **Locate** the actual screen, route entry point, shared shell, styles, state, API calls and transitions. Read the canonical sources above; do not redesign from memory or a screenshot alone.
2. **Compare** against the customer-booking baseline: typography, color contrast, surface depth, radii, spacing, icons, header, bottom action/navigation, selected underline, animations and screen states. Note exact existing CSS class/token to reuse. Fix root causes before adding override-on-override CSS.
3. **Build minimally** on existing UI components and routes. No parallel alternative shells and no UI-only fake buttons. Preserve company selection, permission checks, navigation, browser history, dialogs, uploads and business flows. Verify active state is based on actual route/state rather than appearance alone.
4. **Verify functionality**: click/tap all changed actions and links and confirm expected screen/data; back/close should return to the correct parent instead of closing the browser tab; test populated, empty, loading, error and long-content states. If an external backend or credentials are unavailable, use isolated realistic mock data only for UI testing and report the limitation.
5. **Verify rendered pixels**, not just code: use available browser automation or screenshots of the **real rendered route** at 360px, 390px and 430px phone widths; a short phone viewport (~640px); desktop (>=1024px); light and dark where supported. Examine both whole page and close-up of navigation/selected underline, plus interaction screenshots. Check clipping, horizontal overflow, offscreen controls, incorrect layering/z-index, safe areas, text contrast, inconsistent font/rounding, active underline geometry and component alignment. Compare to actual booking UI/baseline. Do not declare a visual pass without seeing a rendering. Automated screenshot capture must be executed, not merely described.
6. **Regression**: run existing targeted tests and relevant browser checks, review diff for unrelated CSS changes, then follow repository `AGENTS.md` policy for CI. For screenshot-diff tests, review visual differences rather than approving a changed baseline blindly.
7. **Report truthfully**: provide files/paths changed, baseline checked, phone/desktop/theme and interactions actually tested, failures and anything **not** inspected; distinguish static review from browser evidence.

### ServGo-specific high-priority regression scenarios

- Studio's bottom navigation line must match BookingBot's tapered flowing line, not a flat shape or an oversized bar; all icons, labels and active state remain vertically aligned.
- Leaving Mail, SEO factory, Content factory or opening a finished video must **navigate/show content**, not silently close a tab or window. Test actual destination links and back navigation.
- Business switcher must preserve the correct owner/company context and must not accidentally display another tenant's data.
- Bell icon centered in its hit area; logo visible in both themes; contrast of dark-theme muted text and buttons; notification/status text properly spaced; video cards and loading states coherent.
- Long company profile imports, uploads and action buttons preserve functionality; visual-only fixes never change content limits or processing rules.

## Acceptance checklist

A UI change is not complete unless: (a) it looks like ServGo Air from the booking journey; (b) available controls work; (c) phone + desktop rendering has been inspected; (d) dark theme is checked if supported; (e) tests and scope of verification are accurately reported. If visual inspection is unavailable, mark UI QA **not verified** rather than green.

## Scope / safety

- Preserve the tenant-isolation rule in `docs/architecture/SERVGO_SAAS_RULE.md`; UI redesign is not an excuse to loosen auth or authorization.
- Do not modify API contracts, payment/prepayment semantics, scheduling or publishing logic as a side effect of design cleanup.
- Never publish screenshots containing real client data, cookies, credentials or private company records.
- No production deploy as part of merely creating/updating this skill; deployments follow existing guarded workflows.
- Inspiration from the Stageshow review method is **visual validation and iteration**, not importing its styles, components, brand or motion choreography into ServGo.
