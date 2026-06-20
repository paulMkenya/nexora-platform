# DS integration — resume notes

- platform_leads owner pipeline table deferred to Surface 4 (renders in admin_shared/nav.html; styled with operator console after money/impersonation server-side audit).
- affiliate_ui payouts pages (payouts.views.affiliate_views) + admin_affiliates deferred to Surface 4 (money + operator surfaces, after server-side enforcement audit).
- REACT ISLAND PREREQUISITE: _ds_bundle.js externalizes React (no React inlined) and ships with Babel-in-browser/SPA mount examples we banned. ANY future island requires first vendoring react.production.min.js + react-dom.production.min.js into static/vendor/ and hand-writing createElement mounts (no JSX, no Babel). This is a separate spike, not a surface task. No islands until that spike is done and approved.

## Surface log

### Surface 1 — platform_leads (public /get-started/) — commit a0db1ea
- CSS-only, server-rendered, no island. Rebound :root + color literals to DS semantic tokens (data-brand=nexora, theme-dark).
- Honeypot hp_check, server-side validation, all form field names unchanged. Per-tenant brand-color override preserved (DS tokens are fallback).
- Owner pipeline table deferred to Surface 4.
- Verified (fresh stack): GET 200, DS link/tokens served, valid POST creates lead, honeypot POST drops bot (0 leads).

### Surface 2 — affiliate_ui portal — commit 5f3cf7e
- CSS-only, no island. base.html: added data-brand="nexora" (activated dormant blue->teal). style.css: DS-token rules for card headers, form controls, .bg-light, table heads, badges; report tables get --status-* on approved/hold/rejected columns; dashboard stat tiles get DS tokens.
- Affiliate has NO per-tenant accent injection (native contract scopes per-brand ACCENT to advertiser shells); token-only, zero hardcoded hex -> nothing to override.
- No view/logic changes; bundle unreferenced. Deferred: affiliate payouts pages + admin_affiliates -> Surface 4.
- Verified (fresh stack, test Client): brand layer active on dashboard/reports/offers/login; status classes render on a seeded data row; offers/login covered; no hardcoded hex.

### Surface 3 — advertiser_ui portal — (this commit)
- CSS-only, no island. Touched base.html (+ new advertiser_ui/static/advertiser_ui/css/style.css). No per-template markup edits.
- KEY per-tenant finding: advertiser shell injected brand.primary into tailwind.config but NO template ever used `brand-*` — accent was hardcoded `indigo-*` (50 uses), so per-tenant accent was DEAD (never reached UI).
- Fix: (a) inline :root accent bridge sources --brand-primary/secondary from brand.primary_color/secondary_color (default Nexora #2E8FF0/#16D9A3); (b) tailwind.config remaps `indigo`->var(--brand-*) (+ color-mix tints) and green/yellow/red->DS --status-* tokens; (c) new stylesheet remaps the fixed-light NEUTRAL palette (bg-white/gray text+surface+border, inputs) to DS tokens, scoped to [data-theme="dark"] .nx-content only.
- PER-TENANT GUARANTEE HELD + FIXED: accent flows from --brand-primary = brand record, so per-tenant WINS over DS fallback. Deliberately did NOT add data-brand="nexora" (would pin --brand-primary to Nexora and override the tenant) — flagged + avoided.
- No view/logic changes; bundle unreferenced; no SPA/Babel; token-only (zero hardcoded hex in advertiser CSS).
- Surface 4 deferrals: wallet.html (advertiser money surface, READ-ONLY display; gets incidental chrome theming via base.html, no money components/audit here). No operator surfaces in advertiser_ui.
- Verified (fresh stack, test Client): custom tenant #FF5733/#00CC88 WINS over DS fallback; no-custom -> Nexora #2E8FF0/#16D9A3; dashboard/offers/conversions/settings/wallet/login all 200; indigo->brand var + status->DS tokens present.
