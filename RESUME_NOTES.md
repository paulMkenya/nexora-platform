# DS integration — resume notes

## ✅ STATUS: LIVE IN PRODUCTION — RESUME FROM HERE (deployed 2026-06-20)

PR #14 merged to `main` (`25c9b08`) and **deployed to prod** `cpa.cloudtrade.pro`.
- Running image: `nexora-platform:latest` = `c78fa865a006` (built from `25c9b08`).
- Migration applied: `user_profile.0009_profile_theme_preference` (additive column; no money tables).
- Smoke test passed: login/advertiser-login/get-started = 200; money routes (`/partner/payouts/`, `/admin/payouts/`) = 302 auth-gate (no 500); all DS assets 200; no errors in logs; web/worker/beat healthy.
- ROLLBACK (still valid): image `4a56aa66` = tag `nexora-platform:pre-ds-rollback-20260620-074212`; DB dump `/home/paul/cloudtrade_main_pre-ds-deploy_20260620-074212.dump` (copied off-host by user); record `/home/paul/ROLLBACK_pre-ds-deploy_20260620-074212.txt`. Rollback = retag that image to :latest + `compose up -d` (additive migration needs no DB restore).

### NEXT STEPS when we resume (in priority order)
1. **Logged-in visual pass (owner's task):** click-through one affiliate money page (`/partner/payouts/`) + one operator money page (`/admin/payouts/`) while authenticated — only thing not exercised on prod (no test users created on prod). Everything else verified.
2. **Operator-console standalone restyle** (DEFERRED from Surface 4): payout console (admin_payout_list/holds/control_settings/batches), platform_leads pipeline, admin_affiliates/detail, /admin/* dashboard/fraud/brands. These are light Bootstrap docs; DS-wiring them needs a per-page body restyle (DS base.css themes <body>) — the codebase's planned "later PR". Do as its own surface/PR.
3. **2.2MB default logo** (DEFERRED perf): replace `static/img/nexora-logo.png` (2.2MB @ ~40px) with an optimized SVG/PNG before heavy go-live traffic.
4. **React-island spike** (only if a real data-dense island is needed): vendor react/react-dom into static/vendor/ + hand-write createElement mounts (no JSX/Babel). Not started.
5. **Housekeeping (optional):** `chown -R deploy:deploy /opt/nexora-platform` (this deploy wrote files as paul via deploy-group); delete merged branch `feat/design-system-integration` (local+remote) when ready; `unified-shell-ref`/`a1cecda` abandoned (kept as ref).

---

- platform_leads owner pipeline table deferred to Surface 4 (renders in admin_shared/nav.html; styled with operator console after money/impersonation server-side audit).
- affiliate_ui payouts pages (payouts.views.affiliate_views) + admin_affiliates deferred to Surface 4 (money + operator surfaces, after server-side enforcement audit).
- REACT ISLAND PREREQUISITE: _ds_bundle.js externalizes React (no React inlined) and ships with Babel-in-browser/SPA mount examples we banned. ANY future island requires first vendoring react.production.min.js + react-dom.production.min.js into static/vendor/ and hand-writing createElement mounts (no JSX, no Babel). This is a separate spike, not a surface task. No islands until that spike is done and approved.
- DEFERRED GO-LIVE PERF: default fallback logo nexora-logo.png is 2.2MB rendered at ~40px — replace with optimized SVG before go-live. (PR #14 code-review finding #2, deferred — needs a replacement optimized asset.)

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

### Surface 4 — operator-console / impersonation / payouts — (this commit)

**SERVER-SIDE ENFORCEMENT AUDIT (HARD STOP gate) — PASSED. Cleared to wire.**
Proven empirically on a fresh one-shot stack (test Client), not just by reading:
- Money actions are authorized SERVER-SIDE independent of MoneyConfirm (UX-only, absent from these server-rendered pages):
  - operator views (payouts/views/admin_views.py): @staff_member_required + brand-scoping (_scope_payouts).
  - affiliate views (payouts/views/affiliate_views.py): @require_approved_affiliate.
  - TEST 2: non-staff POST to /admin/payouts/{approve,mark-paid,dispatch,controls}/ -> 302->login (denied).
- Impersonating sessions are BLOCKED from EVERY money action server-side via @block_when_impersonating (impersonation/decorators.py), outermost decorator -> 403 before any handler:
  - TEST 1: impersonated POST to all 7 money endpoints (affiliate request/methods-add/settings + operator approve/mark-paid/dispatch/controls) -> 403 "disabled during impersonation".
  - TEST 3: a normal (non-impersonated) affiliate is NOT blocked (302 success) -> the control is the decorator, not the UI.
- Impersonation middleware re-validates scope on every request (impersonation/permissions.scoped_target): superuser never a target, never sideways/upward, archived/deactivated excluded; persistent red banner ("Money actions are disabled") is intentionally never themed.
- CONCLUSION: no BLOCKER. Both hard-stop conditions enforced server-side.

**UI wiring done (CSS-only):**
- affiliate-facing money UI (affiliate_payouts.html) already inherits the DS shell (it extends affiliate_ui/base.html, wired in Surface 2). Completed its theming in affiliate_ui/css/style.css: payout status badges (bg-success/warning/danger) + semantic text utils (text-success/warning/danger) -> DS --status-* tokens. Token-only, scoped to .nx-content.
- Synced affiliate_ui/tests/test_dashboard.py exact-markup assertions to the DS stat-card classes added in Surface 2 (presentation assertion, not logic).

**DEFERRED (operator console standalone Bootstrap pages):** payout console (admin_payout_list / admin_holds_list / admin_control_settings / admin_batch_list), platform_leads pipeline (pipeline/lead_detail/settings), affiliate_ui admin_affiliates/admin_affiliate_detail, impersonation/log.html, and the broader /admin/* dashboard/fraud/brands pages.
- REASON: these are standalone LIGHT Bootstrap docs (own <html>, Bootstrap CDN, included admin_shared/nav.html forces data-theme=dark on <html>). Naively linking ds/styles.css there pulls DS base.css which themes the `body` element -> unpredictable cascade vs light-assuming Bootstrap content = regression risk. A safe pass requires the full per-page body restyle, which the codebase ITSELF already plans as a later PR (see admin_shared/nav.html comment: "the grouped-sidebar conversion of the 20 admin pages is a later PR"). Out of scope for a bounded CSS-layer pass; not wired around — left for that dedicated operator-console PR.
- The shared admin_shared/nav.html already renders on the native token layer (consistent dark nav); the impersonation banner is intentionally unthemed. No regression introduced.

**Tests:** targeted suites for all touched apps (affiliate_ui, advertiser_ui, platform_leads, payouts, impersonation) = 430 passed, 0 failed (the one initial failure was the dashboard markup assertion above, now synced).

---

## FINAL SUMMARY — DS integration on branch `feat/design-system-integration`

Base: `main`. All work committed to the feature branch. NOT pushed, NOT merged (user does that).

| Commit | Surface | What it wired |
|--------|---------|---------------|
| 239960d | checkpoint | DS drop-in: static/ds/ (styles.css + tokens + precompiled _ds_bundle.js, unreferenced) + base.html DS links + preview.py |
| a0db1ea | 1 platform_leads | public /get-started/ -> DS tokens (CSS-only); honeypot/validation/fields untouched |
| 5f3cf7e | 2 affiliate_ui | portal -> DS (data-brand=nexora; cards/forms/tables/badges/status; report status columns) |
| 39e9e64 | 3 advertiser_ui | portal -> DS; REVIVED dead per-tenant accent (indigo->brand var) + dark neutral remap |
| (this)  | 4 payouts/impersonation | enforcement audit PASSED; affiliate payout status badges -> DS; operator console deferred |

**Per-tenant accent handling (advertiser, the KEY item):** the shell injected brand.primary into tailwind.config but no template used `brand-*` (accent was hardcoded indigo -> per-tenant was DEAD). Fixed via inline :root bridge (--brand-primary/secondary <- brand.primary_color/secondary_color, default Nexora #2E8FF0/#16D9A3) + tailwind.config indigo->var(--brand-*). Per-tenant WINS over DS fallback; verified custom #FF5733 resolves on the shell. Did NOT add data-brand="nexora" (would override the tenant). Affiliate/leads have no per-tenant accent (native contract scopes ACCENT to advertiser shells) -> token-only, nothing to override.

**Rendering strategy honored:** server-rendered Django everywhere; CSS-token layer only; NO islands, NO SPA, NO Babel; _ds_bundle.js never referenced (React-island prerequisite spike still pending — see note above).

**Verification:** every surface checked on a FRESH one-shot stack (throwaway Postgres+Redis, preview settings, test Client). The long-running nx-preview-web was found serving stale templates and was removed. Targeted test suites: 430 passed / 0 failed.

**EXACT COMMANDS (for the user — I did not run these):**
```bash
# Review the trail
git -C /home/paul/nexora-platform log --oneline main..feat/design-system-integration
git -C /home/paul/nexora-platform diff --stat main...feat/design-system-integration

# Push the feature branch (no PR yet)
git -C /home/paul/nexora-platform push -u origin feat/design-system-integration

# Merge to main locally (only after review) — no-ff keeps the surface history
git -C /home/paul/nexora-platform checkout main
git -C /home/paul/nexora-platform merge --no-ff feat/design-system-integration
git -C /home/paul/nexora-platform push origin main

# ROLLBACK options
# a) discard the branch entirely (nothing merged): 
git -C /home/paul/nexora-platform branch -D feat/design-system-integration
# b) undo a pushed merge on main (revert the merge commit, keep history):
git -C /home/paul/nexora-platform revert -m 1 <merge_commit_sha>
# c) drop a single surface before merging (interactive not available here; use revert):
git -C /home/paul/nexora-platform revert <surface_commit_sha>
```
Production deploy is a separate step (CLAUDE.md: build Dockerfile.prod + compose up on /opt as the `deploy` user, collectstatic runs on nexora-web startup). NOT done here.
