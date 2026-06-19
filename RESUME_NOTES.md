# DS integration — resume notes

- platform_leads owner pipeline table deferred to Surface 4 (renders in admin_shared/nav.html; styled with operator console after money/impersonation server-side audit).
- affiliate_ui payouts pages (payouts.views.affiliate_views) + admin_affiliates deferred to Surface 4 (money + operator surfaces, after server-side enforcement audit).
- REACT ISLAND PREREQUISITE: _ds_bundle.js externalizes React (no React inlined) and ships with Babel-in-browser/SPA mount examples we banned. ANY future island requires first vendoring react.production.min.js + react-dom.production.min.js into static/vendor/ and hand-writing createElement mounts (no JSX, no Babel). This is a separate spike, not a surface task. No islands until that spike is done and approved.
