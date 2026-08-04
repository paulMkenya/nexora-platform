/* @ds-bundle: {"format":3,"namespace":"NexoraDesignSystem_985ae7","components":[{"name":"Button","sourcePath":"components/buttons/Button.jsx"},{"name":"IconButton","sourcePath":"components/buttons/IconButton.jsx"},{"name":"DataTable","sourcePath":"components/data/DataTable.jsx"},{"name":"FilterBar","sourcePath":"components/data/FilterBar.jsx"},{"name":"StatTile","sourcePath":"components/data/StatTile.jsx"},{"name":"Avatar","sourcePath":"components/display/Avatar.jsx"},{"name":"Badge","sourcePath":"components/display/Badge.jsx"},{"name":"Card","sourcePath":"components/display/Card.jsx"},{"name":"CardHeader","sourcePath":"components/display/Card.jsx"},{"name":"StatusPill","sourcePath":"components/display/StatusPill.jsx"},{"name":"EmptyState","sourcePath":"components/feedback/EmptyState.jsx"},{"name":"ImpersonationBanner","sourcePath":"components/feedback/ImpersonationBanner.jsx"},{"name":"Modal","sourcePath":"components/feedback/Modal.jsx"},{"name":"MoneyConfirm","sourcePath":"components/feedback/MoneyConfirm.jsx"},{"name":"Toast","sourcePath":"components/feedback/Toast.jsx"},{"name":"ToastViewport","sourcePath":"components/feedback/Toast.jsx"},{"name":"Checkbox","sourcePath":"components/forms/Checkbox.jsx"},{"name":"Input","sourcePath":"components/forms/Input.jsx"},{"name":"Select","sourcePath":"components/forms/Select.jsx"},{"name":"Icon","sourcePath":"components/icon/Icon.jsx"},{"name":"Sidebar","sourcePath":"components/navigation/Sidebar.jsx"},{"name":"Topbar","sourcePath":"components/navigation/Topbar.jsx"}],"sourceHashes":{"components/buttons/Button.jsx":"943b84b4191a","components/buttons/IconButton.jsx":"2a9d3ea14148","components/data/DataTable.jsx":"1fbcbcca747e","components/data/FilterBar.jsx":"c3fcb9b63ec1","components/data/StatTile.jsx":"938f3039b9cd","components/display/Avatar.jsx":"44247f275bee","components/display/Badge.jsx":"076fd2be6697","components/display/Card.jsx":"c4f47acf693f","components/display/StatusPill.jsx":"bb8666d5be63","components/feedback/EmptyState.jsx":"5f7908bf7663","components/feedback/ImpersonationBanner.jsx":"8ec9f68d778b","components/feedback/Modal.jsx":"9989949cbd70","components/feedback/MoneyConfirm.jsx":"13c3f746f07b","components/feedback/Toast.jsx":"af8299f3916a","components/forms/Checkbox.jsx":"e2aefa694ad3","components/forms/Input.jsx":"9141ff8d492c","components/forms/Select.jsx":"6559e8f43cc2","components/icon/Icon.jsx":"781195777aa4","components/navigation/Sidebar.jsx":"48b7e705e797","components/navigation/Topbar.jsx":"9f2ad2b759c3","ui_kits/advertiser/screens.jsx":"aa9e9089becf","ui_kits/affiliate/screens.jsx":"2282ee831246","ui_kits/affiliate/tweaks-panel.jsx":"6591467622ed","ui_kits/marketing/screens.jsx":"f0294347f687","ui_kits/operator/screens.jsx":"e2d69ad099b6"},"inlinedExternals":[],"unexposedExports":[{"name":"iconNames","sourcePath":"components/icon/Icon.jsx"}]} */

(() => {

const __ds_ns = (window.NexoraDesignSystem_985ae7 = window.NexoraDesignSystem_985ae7 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/display/Avatar.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Avatar — initials or image chip for affiliates, advertisers, operators. */
const SIZES = {
  xs: 22,
  sm: 28,
  md: 36,
  lg: 44
};
function hueFrom(str = "") {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) % 360;
  return h;
}
function Avatar({
  name = "",
  src,
  size = "md",
  square = false,
  style = {},
  ...rest
}) {
  const px = SIZES[size] || SIZES.md;
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0]?.toUpperCase()).join("") || "—";
  const hue = hueFrom(name);
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: px,
      height: px,
      flexShrink: 0,
      borderRadius: square ? "var(--radius-sm)" : "var(--radius-full)",
      background: src ? "var(--surface-sunken)" : `hsl(${hue} 52% 42%)`,
      color: "#fff",
      fontSize: px * 0.38,
      fontWeight: "var(--weight-semibold)",
      overflow: "hidden",
      userSelect: "none",
      ...style
    }
  }, rest), src ? /*#__PURE__*/React.createElement("img", {
    src: src,
    alt: name,
    style: {
      width: "100%",
      height: "100%",
      objectFit: "cover"
    }
  }) : initials);
}
Object.assign(__ds_scope, { Avatar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/Avatar.jsx", error: String((e && e.message) || e) }); }

// components/display/Badge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Badge — small categorical label (vertical, revenue model, count, tag). Quieter than StatusPill. */
const TONES = {
  neutral: {
    bg: "var(--status-neutral-bg)",
    fg: "var(--status-neutral-fg)"
  },
  brand: {
    bg: "var(--brand-tint)",
    fg: "var(--brand-tint-fg)"
  },
  info: {
    bg: "var(--status-info-bg)",
    fg: "var(--status-info-fg)"
  },
  positive: {
    bg: "var(--status-positive-bg)",
    fg: "var(--status-positive-fg)"
  },
  warning: {
    bg: "var(--status-warning-bg)",
    fg: "var(--status-warning-fg)"
  },
  danger: {
    bg: "var(--status-danger-bg)",
    fg: "var(--status-danger-fg)"
  }
};
function Badge({
  children,
  tone = "neutral",
  outline = false,
  style = {},
  ...rest
}) {
  const t = TONES[tone] || TONES.neutral;
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
      display: "inline-flex",
      alignItems: "center",
      padding: "2px 8px",
      fontSize: "var(--text-xs)",
      fontWeight: "var(--weight-medium)",
      lineHeight: 1.5,
      borderRadius: "var(--radius-sm)",
      background: outline ? "transparent" : t.bg,
      color: t.fg,
      border: outline ? `1px solid ${t.fg}` : "1px solid transparent",
      whiteSpace: "nowrap",
      ...style
    }
  }, rest), children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/Badge.jsx", error: String((e && e.message) || e) }); }

// components/display/Card.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Card — the base surface for panels, tables and grouped content. */
function Card({
  children,
  padding = "lg",
  interactive = false,
  style = {},
  ...rest
}) {
  const pad = {
    none: 0,
    sm: "var(--space-4)",
    md: "var(--space-5)",
    lg: "var(--space-6)"
  }[padding] ?? "var(--space-6)";
  const [hover, setHover] = React.useState(false);
  return /*#__PURE__*/React.createElement("div", _extends({
    onMouseEnter: interactive ? () => setHover(true) : undefined,
    onMouseLeave: interactive ? () => setHover(false) : undefined,
    style: {
      background: "var(--surface-card)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-md)",
      boxShadow: hover ? "var(--shadow-md)" : "var(--shadow-sm)",
      padding: pad,
      transition: "box-shadow .18s ease, transform .18s ease, border-color .18s ease",
      transform: hover ? "translateY(-2px)" : "none",
      cursor: interactive ? "pointer" : "default",
      ...style
    }
  }, rest), children);
}

/** CardHeader — title row with optional actions, sits flush at a Card's top. */
function CardHeader({
  title,
  subtitle,
  actions,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "flex-start",
      justifyContent: "space-between",
      gap: "var(--space-4)",
      marginBottom: "var(--space-4)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h3", {
    style: {
      fontSize: "var(--text-lg)",
      fontWeight: "var(--weight-semibold)"
    }
  }, title), subtitle ? /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: "var(--text-sm)",
      color: "var(--text-muted)",
      marginTop: 2
    }
  }, subtitle) : null), actions ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "var(--space-2)",
      flexShrink: 0
    }
  }, actions) : null);
}
Object.assign(__ds_scope, { Card, CardHeader });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/Card.jsx", error: String((e && e.message) || e) }); }

// components/icon/Icon.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Nexora icon set — Lucide (https://lucide.dev), ISC-licensed.
 * Lucide is the platform's icon system: 24×24, 2px stroke, round
 * caps/joins, no fill. We embed only the glyphs the product uses so
 * the bundle stays self-contained (no CDN, no npm). Add more by
 * pasting the Lucide path data into PATHS below.
 */
const PATHS = {
  "layout-dashboard": '<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>',
  tag: '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/>',
  "bar-chart": '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
  "arrow-left-right": '<path d="M8 3 4 7l4 4"/><path d="M4 7h16"/><path d="m16 21 4-4-4-4"/><path d="M20 17H4"/>',
  wallet: '<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/>',
  settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  "log-out": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  pause: '<rect x="14" y="3" width="5" height="18" rx="1"/><rect x="5" y="3" width="5" height="18" rx="1"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  "chevron-down": '<path d="m6 9 6 6 6-6"/>',
  "chevron-right": '<path d="m9 18 6-6-6-6"/>',
  "chevron-up": '<path d="m18 15-6-6-6 6"/>',
  "chevrons-up-down": '<path d="m7 15 5 5 5-5"/><path d="m7 9 5-5 5 5"/>',
  "arrow-up": '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
  "arrow-down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  building: '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>',
  "shield-check": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
  "alert-triangle": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  "file-text": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
  eye: '<path d="M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0"/><circle cx="12" cy="12" r="3"/>',
  copy: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  "external-link": '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  "dollar-sign": '<line x1="12" x2="12" y1="2" y2="22"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
  "trending-up": '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
  "mouse-pointer-click": '<path d="M14 4.1 12 6"/><path d="m5.1 8-2.9-.8"/><path d="m6 12-1.9 2"/><path d="M7.2 2.2 8 5.1"/><path d="M9.037 9.69a.498.498 0 0 1 .653-.653l11 4.5a.5.5 0 0 1-.074.949l-4.349 1.041a1 1 0 0 0-.74.739l-1.04 4.35a.5.5 0 0 1-.95.074z"/>',
  target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  ban: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
  "check-circle": '<path d="M21.8 10A10 10 0 1 1 17 3.34"/><path d="m9 11 3 3L22 4"/>',
  hourglass: '<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.17a2 2 0 0 0-.59-1.41L12 12l-4.41 4.41A2 2 0 0 0 7 17.83V22"/><path d="M7 2v4.17a2 2 0 0 0 .59 1.41L12 12l4.41-4.41A2 2 0 0 0 17 6.17V2"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  menu: '<line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="18" y2="18"/>',
  filter: '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
  lock: '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  "credit-card": '<rect width="20" height="14" x="2" y="5" rx="2"/><line x1="2" x2="22" y1="10" y2="10"/>',
  bell: '<path d="M10.27 21a2 2 0 0 0 3.46 0"/><path d="M3.26 15.33A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.67C19.41 13.96 18 12.5 18 8A6 6 0 0 0 6 8c0 4.5-1.41 5.96-2.74 7.33"/>',
  "help-circle": '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
  "more-horizontal": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  "refresh-cw": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M3 21v-5h5"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  "arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  globe: '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
  zap: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>'
};
function Icon({
  name,
  size = 18,
  strokeWidth = 2,
  className = "",
  style = {},
  title,
  ...rest
}) {
  const d = PATHS[name];
  return /*#__PURE__*/React.createElement("svg", _extends({
    xmlns: "http://www.w3.org/2000/svg",
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: strokeWidth,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    className: className,
    style: {
      flexShrink: 0,
      display: "block",
      ...style
    },
    "aria-hidden": title ? undefined : true,
    role: title ? "img" : undefined
  }, rest), title ? /*#__PURE__*/React.createElement("title", null, title) : null, d ? /*#__PURE__*/React.createElement("g", {
    dangerouslySetInnerHTML: {
      __html: d
    }
  }) : null);
}

/** Names available in the embedded set — handy for specimen grids. */
const iconNames = Object.keys(PATHS);
Object.assign(__ds_scope, { Icon, iconNames });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/icon/Icon.jsx", error: String((e && e.message) || e) }); }

// components/buttons/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Button — the platform's primary action control.
 * Variants: primary (brand fill), secondary (outline), ghost (text),
 * danger (destructive). Brand variants follow --brand-primary so a
 * tenant's color flows through automatically.
 */
const SIZES = {
  sm: {
    padding: "6px 12px",
    font: "var(--text-sm)",
    gap: "6px",
    icon: 15,
    height: "32px"
  },
  md: {
    padding: "9px 16px",
    font: "var(--text-base)",
    gap: "8px",
    icon: 17,
    height: "40px"
  },
  lg: {
    padding: "12px 22px",
    font: "var(--text-md)",
    gap: "9px",
    icon: 19,
    height: "48px"
  }
};
function Button({
  children,
  variant = "primary",
  size = "md",
  iconLeft,
  iconRight,
  loading = false,
  disabled = false,
  full = false,
  type = "button",
  style = {},
  ...rest
}) {
  const s = SIZES[size] || SIZES.md;
  const isDisabled = disabled || loading;
  const base = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: s.gap,
    padding: s.padding,
    minHeight: s.height,
    width: full ? "100%" : "auto",
    fontFamily: "var(--font-sans)",
    fontSize: s.font,
    fontWeight: "var(--weight-semibold)",
    lineHeight: 1,
    borderRadius: "var(--radius-sm)",
    border: "1px solid transparent",
    cursor: isDisabled ? "not-allowed" : "pointer",
    opacity: isDisabled ? 0.55 : 1,
    transition: "background .15s ease, border-color .15s ease, color .15s ease, box-shadow .15s ease, transform .05s ease",
    whiteSpace: "nowrap",
    userSelect: "none"
  };
  const variants = {
    primary: {
      background: "var(--brand-primary)",
      color: "var(--brand-primary-fg)",
      borderColor: "var(--brand-primary)"
    },
    secondary: {
      background: "var(--surface-card)",
      color: "var(--text-body)",
      borderColor: "var(--border-strong)"
    },
    ghost: {
      background: "transparent",
      color: "var(--text-body)",
      borderColor: "transparent"
    },
    danger: {
      background: "var(--status-danger-solid)",
      color: "#fff",
      borderColor: "var(--status-danger-solid)"
    }
  };
  const [hover, setHover] = React.useState(false);
  const [active, setActive] = React.useState(false);
  const hoverStyle = !isDisabled && hover ? {
    primary: {
      background: "var(--brand-secondary)",
      borderColor: "var(--brand-secondary)"
    },
    secondary: {
      background: "var(--surface-sunken)",
      borderColor: "var(--border-strong)"
    },
    ghost: {
      background: "var(--surface-sunken)"
    },
    danger: {
      background: "var(--red-700)",
      borderColor: "var(--red-700)"
    }
  }[variant] : {};
  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    disabled: isDisabled,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => {
      setHover(false);
      setActive(false);
    },
    onMouseDown: () => setActive(true),
    onMouseUp: () => setActive(false),
    style: {
      ...base,
      ...variants[variant],
      ...hoverStyle,
      transform: active && !isDisabled ? "translateY(1px)" : "none",
      ...style
    }
  }, rest), loading ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "refresh-cw",
    size: s.icon,
    style: {
      animation: "nx-spin 1s linear infinite"
    }
  }) : iconLeft ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: iconLeft,
    size: s.icon
  }) : null, children, !loading && iconRight ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: iconRight,
    size: s.icon
  }) : null, /*#__PURE__*/React.createElement("style", null, "@keyframes nx-spin{to{transform:rotate(360deg)}}"));
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/buttons/Button.jsx", error: String((e && e.message) || e) }); }

// components/buttons/IconButton.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** IconButton — square, icon-only control for toolbars, table rows, top bars. */
const SIZES = {
  sm: {
    box: 30,
    icon: 16
  },
  md: {
    box: 38,
    icon: 18
  },
  lg: {
    box: 44,
    icon: 20
  }
};
function IconButton({
  icon,
  label,
  variant = "ghost",
  size = "md",
  disabled = false,
  style = {},
  ...rest
}) {
  const s = SIZES[size] || SIZES.md;
  const [hover, setHover] = React.useState(false);
  const variants = {
    ghost: {
      background: hover ? "var(--surface-sunken)" : "transparent",
      color: "var(--text-muted)",
      border: "1px solid transparent"
    },
    outline: {
      background: hover ? "var(--surface-sunken)" : "var(--surface-card)",
      color: "var(--text-body)",
      border: "1px solid var(--border-strong)"
    },
    danger: {
      background: hover ? "var(--status-danger-bg)" : "transparent",
      color: "var(--status-danger-fg)",
      border: "1px solid transparent"
    }
  };
  return /*#__PURE__*/React.createElement("button", _extends({
    type: "button",
    "aria-label": label,
    title: label,
    disabled: disabled,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: s.box,
      height: s.box,
      borderRadius: "var(--radius-sm)",
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.5 : 1,
      transition: "background .15s ease, color .15s ease",
      ...variants[variant],
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon,
    size: s.icon
  }));
}
Object.assign(__ds_scope, { IconButton });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/buttons/IconButton.jsx", error: String((e && e.message) || e) }); }

// components/data/DataTable.jsx
try { (() => {
/**
 * DataTable — dense, sortable table for affiliates, offers, conversions,
 * payouts. Columns: { key, header, align, sortable, render, mono, width }.
 * Sorting is internal by default (string/number aware); pass `onSort` to
 * control it externally. Header is uppercase micro-label; rows hover-tint.
 */
function DataTable({
  columns = [],
  rows = [],
  rowKey,
  dense = false,
  onRowClick,
  sort: sortProp,
  onSort,
  empty = "No records found.",
  style = {}
}) {
  const [sortInner, setSortInner] = React.useState(null);
  const sort = sortProp !== undefined ? sortProp : sortInner;
  const handleSort = col => {
    if (!col.sortable) return;
    const next = !sort || sort.key !== col.key ? {
      key: col.key,
      dir: "asc"
    } : {
      key: col.key,
      dir: sort.dir === "asc" ? "desc" : "asc"
    };
    if (onSort) onSort(next);else setSortInner(next);
  };
  let view = rows;
  if (sortProp === undefined && sort) {
    const col = columns.find(c => c.key === sort.key);
    if (col) {
      view = [...rows].sort((a, b) => {
        const av = a[sort.key],
          bv = b[sort.key];
        const n = typeof av === "number" && typeof bv === "number" ? av - bv : String(av ?? "").localeCompare(String(bv ?? ""));
        return sort.dir === "asc" ? n : -n;
      });
    }
  }
  const cellPad = dense ? "8px 14px" : "12px 16px";
  return /*#__PURE__*/React.createElement("div", {
    style: {
      overflowX: "auto",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-md)",
      background: "var(--surface-card)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("table", {
    style: {
      width: "100%",
      borderCollapse: "collapse",
      fontSize: dense ? "var(--text-sm)" : "var(--text-base)"
    }
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", {
    style: {
      background: "var(--surface-sunken)"
    }
  }, columns.map(c => {
    const active = sort && sort.key === c.key;
    return /*#__PURE__*/React.createElement("th", {
      key: c.key,
      onClick: () => handleSort(c),
      style: {
        padding: cellPad,
        textAlign: c.align || "left",
        fontSize: "var(--text-xs)",
        fontWeight: "var(--weight-semibold)",
        textTransform: "uppercase",
        letterSpacing: "var(--tracking-wide)",
        color: active ? "var(--text-body)" : "var(--text-muted)",
        whiteSpace: "nowrap",
        cursor: c.sortable ? "pointer" : "default",
        borderBottom: "1px solid var(--border-default)",
        userSelect: "none",
        width: c.width
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        justifyContent: c.align === "right" ? "flex-end" : "flex-start"
      }
    }, c.header, c.sortable ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
      name: active ? sort.dir === "asc" ? "arrow-up" : "arrow-down" : "chevrons-up-down",
      size: 12,
      strokeWidth: 2.5,
      style: {
        opacity: active ? 1 : 0.5
      }
    }) : null));
  }))), /*#__PURE__*/React.createElement("tbody", null, view.length === 0 ? /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("td", {
    colSpan: columns.length,
    style: {
      padding: "48px 16px",
      textAlign: "center",
      color: "var(--text-muted)",
      fontSize: "var(--text-sm)"
    }
  }, empty)) : view.map((row, i) => /*#__PURE__*/React.createElement(Row, {
    key: rowKey ? row[rowKey] : i,
    row: row,
    columns: columns,
    cellPad: cellPad,
    onRowClick: onRowClick,
    last: i === view.length - 1
  })))));
}
function Row({
  row,
  columns,
  cellPad,
  onRowClick,
  last
}) {
  const [hover, setHover] = React.useState(false);
  return /*#__PURE__*/React.createElement("tr", {
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    onClick: onRowClick ? () => onRowClick(row) : undefined,
    style: {
      background: hover ? "var(--surface-sunken)" : "transparent",
      cursor: onRowClick ? "pointer" : "default",
      transition: "background .12s"
    }
  }, columns.map(c => /*#__PURE__*/React.createElement("td", {
    key: c.key,
    style: {
      padding: cellPad,
      textAlign: c.align || "left",
      color: c.muted ? "var(--text-muted)" : "var(--text-body)",
      fontFamily: c.mono ? "var(--font-mono)" : "inherit",
      fontVariantNumeric: c.mono || c.align === "right" ? "tabular-nums lining-nums" : "normal",
      borderBottom: last ? "none" : "1px solid var(--divider)",
      whiteSpace: c.wrap ? "normal" : "nowrap"
    }
  }, c.render ? c.render(row[c.key], row) : row[c.key])));
}
Object.assign(__ds_scope, { DataTable });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/DataTable.jsx", error: String((e && e.message) || e) }); }

// components/data/FilterBar.jsx
try { (() => {
/**
 * FilterBar — the standard control strip above tables (search + selects +
 * apply/reset). A layout shell: drop Input/Select children in, plus an
 * optional trailing actions slot. Sits on a sunken surface.
 */
function FilterBar({
  children,
  actions,
  onReset,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      alignItems: "flex-end",
      gap: "var(--space-3)",
      padding: "var(--space-4)",
      background: "var(--surface-sunken)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-md)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      alignItems: "flex-end",
      gap: "var(--space-3)",
      flex: 1,
      minWidth: 0
    }
  }, children), actions || onReset ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "var(--space-2)",
      alignItems: "flex-end"
    }
  }, actions, onReset ? /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onReset,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      padding: "9px 14px",
      fontSize: "var(--text-sm)",
      fontWeight: "var(--weight-medium)",
      color: "var(--text-muted)",
      background: "transparent",
      border: "1px solid var(--border-strong)",
      borderRadius: "var(--radius-sm)",
      cursor: "pointer"
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "refresh-cw",
    size: 14
  }), " Reset") : null) : null);
}
Object.assign(__ds_scope, { FilterBar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/FilterBar.jsx", error: String((e && e.message) || e) }); }

// components/data/StatTile.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * StatTile — the dashboard metric tile (Clicks / Conversions / Earnings).
 * `accent` makes a money tile pop with the brand tint. `delta` shows a
 * trend chip. Numbers render tabular so columns of tiles align.
 */
function StatTile({
  label,
  value,
  icon,
  delta,
  deltaDir = "up",
  accent = false,
  hint,
  style = {},
  ...rest
}) {
  const deltaTone = deltaDir === "down" ? "var(--status-danger-fg)" : "var(--status-positive-fg)";
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      background: accent ? "var(--brand-tint)" : "var(--surface-card)",
      border: `1px solid ${accent ? "var(--brand-tint-border)" : "var(--border-default)"}`,
      borderRadius: "var(--radius-md)",
      padding: "var(--space-5)",
      boxShadow: "var(--shadow-sm)",
      display: "flex",
      flexDirection: "column",
      gap: 10,
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "var(--text-xs)",
      fontWeight: "var(--weight-semibold)",
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-wider)",
      color: accent ? "var(--brand-tint-fg)" : "var(--text-muted)"
    }
  }, label), icon ? /*#__PURE__*/React.createElement("span", {
    style: {
      color: accent ? "var(--brand-primary)" : "var(--text-faint)"
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon,
    size: 18
  })) : null), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "var(--text-2xl)",
      fontWeight: "var(--weight-bold)",
      lineHeight: 1,
      fontVariantNumeric: "tabular-nums lining-nums",
      color: accent ? "var(--brand-tint-fg)" : "var(--text-strong)"
    }
  }, value), delta ? /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 2,
      fontSize: "var(--text-xs)",
      fontWeight: "var(--weight-semibold)",
      color: deltaTone
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: deltaDir === "down" ? "arrow-down" : "arrow-up",
    size: 12,
    strokeWidth: 3
  }), delta) : null), hint ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "var(--text-xs)",
      color: "var(--text-muted)"
    }
  }, hint) : null);
}
Object.assign(__ds_scope, { StatTile });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/StatTile.jsx", error: String((e && e.message) || e) }); }

// components/display/StatusPill.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * StatusPill — the platform's lifecycle/state token. Maps the product's
 * canonical statuses to a tone + optional icon. Soft tinted by default;
 * `solid` gives a filled dot for extra-loud states (money surfaces).
 */
const STATUS = {
  Approved: {
    tone: "positive",
    icon: "check-circle"
  },
  Activated: {
    tone: "positive",
    icon: "check"
  },
  Paid: {
    tone: "positive",
    icon: "check-circle"
  },
  Verified: {
    tone: "info",
    icon: "shield-check"
  },
  Pending: {
    tone: "warning",
    icon: "hourglass"
  },
  Hold: {
    tone: "warning",
    icon: "pause"
  },
  Held: {
    tone: "warning",
    icon: "pause"
  },
  Processing: {
    tone: "info",
    icon: "refresh-cw"
  },
  Dormant: {
    tone: "neutral",
    icon: "clock"
  },
  Blocked: {
    tone: "danger",
    icon: "ban"
  },
  Rejected: {
    tone: "danger",
    icon: "x"
  },
  Failed: {
    tone: "danger",
    icon: "alert-triangle"
  }
};
const TONE = {
  positive: {
    bg: "var(--status-positive-bg)",
    fg: "var(--status-positive-fg)",
    solid: "var(--status-positive-solid)"
  },
  warning: {
    bg: "var(--status-warning-bg)",
    fg: "var(--status-warning-fg)",
    solid: "var(--status-warning-solid)"
  },
  danger: {
    bg: "var(--status-danger-bg)",
    fg: "var(--status-danger-fg)",
    solid: "var(--status-danger-solid)"
  },
  info: {
    bg: "var(--status-info-bg)",
    fg: "var(--status-info-fg)",
    solid: "var(--status-info-solid)"
  },
  neutral: {
    bg: "var(--status-neutral-bg)",
    fg: "var(--status-neutral-fg)",
    solid: "var(--status-neutral-solid)"
  }
};
function StatusPill({
  status,
  tone,
  label,
  icon,
  dot = false,
  solid = false,
  size = "md",
  style = {},
  ...rest
}) {
  const cfg = STATUS[status] || {};
  const t = TONE[tone || cfg.tone || "neutral"];
  const text = label || status || "";
  const showIcon = icon || (icon === undefined ? cfg.icon : null);
  const sm = size === "sm";
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: sm ? "4px" : "6px",
      padding: sm ? "2px 8px" : "3px 10px",
      fontSize: "var(--text-xs)",
      fontWeight: "var(--weight-semibold)",
      lineHeight: 1.4,
      borderRadius: "var(--radius-full)",
      background: solid ? t.solid : t.bg,
      color: solid ? "#fff" : t.fg,
      whiteSpace: "nowrap",
      ...style
    }
  }, rest), dot ? /*#__PURE__*/React.createElement("span", {
    style: {
      width: 6,
      height: 6,
      borderRadius: "50%",
      background: solid ? "#fff" : t.solid
    }
  }) : showIcon ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: showIcon,
    size: sm ? 11 : 13,
    strokeWidth: 2.5
  }) : null, text);
}
Object.assign(__ds_scope, { StatusPill });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/StatusPill.jsx", error: String((e && e.message) || e) }); }

// components/feedback/EmptyState.jsx
try { (() => {
/** EmptyState — friendly placeholder for empty tables, no offers, no results. */
function EmptyState({
  icon = "file-text",
  title,
  description,
  action,
  compact = false,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      textAlign: "center",
      padding: compact ? "var(--space-8) var(--space-6)" : "var(--space-16) var(--space-6)",
      gap: "var(--space-2)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 52,
      height: 52,
      borderRadius: "var(--radius-lg)",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      background: "var(--surface-sunken)",
      color: "var(--text-faint)",
      marginBottom: "var(--space-2)"
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon,
    size: 24
  })), /*#__PURE__*/React.createElement("h3", {
    style: {
      fontSize: "var(--text-md)",
      fontWeight: "var(--weight-semibold)",
      color: "var(--text-strong)"
    }
  }, title), description ? /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: "var(--text-sm)",
      color: "var(--text-muted)",
      maxWidth: "42ch"
    }
  }, description) : null, action ? /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "var(--space-3)"
    }
  }, action) : null);
}
Object.assign(__ds_scope, { EmptyState });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/EmptyState.jsx", error: String((e && e.message) || e) }); }

// components/feedback/ImpersonationBanner.jsx
try { (() => {
/**
 * ImpersonationBanner — the persistent, loud red bar shown whenever an
 * operator is viewing the product AS another user. Money actions are
 * disabled during impersonation; the banner is never themed (always red)
 * so it cannot be mistaken for normal chrome.
 */
function ImpersonationBanner({
  subjectName,
  subjectRole,
  onExit,
  sticky = true,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    role: "alert",
    style: {
      position: sticky ? "sticky" : "static",
      top: 0,
      zIndex: 60,
      display: "flex",
      alignItems: "center",
      gap: "var(--space-3)",
      padding: "10px var(--space-6)",
      background: "var(--impersonation-bg)",
      color: "var(--impersonation-fg)",
      fontSize: "var(--text-sm)",
      fontWeight: "var(--weight-medium)",
      boxShadow: "0 2px 8px rgba(153,27,27,.4)",
      ...style
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "eye",
    size: 17,
    strokeWidth: 2.5
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1
    }
  }, "Viewing as ", /*#__PURE__*/React.createElement("strong", {
    style: {
      fontWeight: "var(--weight-bold)"
    }
  }, subjectName), subjectRole ? /*#__PURE__*/React.createElement("span", {
    style: {
      opacity: 0.85
    }
  }, " \xB7 ", subjectRole) : null, /*#__PURE__*/React.createElement("span", {
    style: {
      opacity: 0.85
    }
  }, " \u2014 money actions disabled")), onExit ? /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onExit,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      padding: "5px 12px",
      fontSize: "var(--text-xs)",
      fontWeight: "var(--weight-semibold)",
      color: "var(--impersonation-bg)",
      background: "#fff",
      border: "none",
      borderRadius: "var(--radius-sm)",
      cursor: "pointer",
      whiteSpace: "nowrap"
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "log-out",
    size: 13,
    strokeWidth: 2.5
  }), " Exit impersonation") : null);
}
Object.assign(__ds_scope, { ImpersonationBanner });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/ImpersonationBanner.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Modal.jsx
try { (() => {
/** Modal — centered dialog over a scrim. Header / body (children) / footer. */
function Modal({
  open = true,
  title,
  subtitle,
  icon,
  iconTone = "brand",
  onClose,
  footer,
  width = 480,
  children,
  style = {}
}) {
  if (!open) return null;
  const toneColor = {
    brand: {
      bg: "var(--brand-tint)",
      fg: "var(--brand-primary)"
    },
    danger: {
      bg: "var(--status-danger-bg)",
      fg: "var(--status-danger-fg)"
    },
    warning: {
      bg: "var(--status-warning-bg)",
      fg: "var(--status-warning-fg)"
    },
    positive: {
      bg: "var(--status-positive-bg)",
      fg: "var(--status-positive-fg)"
    }
  }[iconTone] || {};
  return /*#__PURE__*/React.createElement("div", {
    onClick: onClose,
    style: {
      position: "fixed",
      inset: 0,
      zIndex: 50,
      background: "var(--surface-overlay)",
      backdropFilter: "blur(2px)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "var(--space-6)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    onClick: e => e.stopPropagation(),
    role: "dialog",
    "aria-modal": "true",
    style: {
      width: "100%",
      maxWidth: width,
      background: "var(--surface-card)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-lg)",
      boxShadow: "var(--shadow-xl)",
      overflow: "hidden",
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "flex-start",
      gap: "var(--space-3)",
      padding: "var(--space-5) var(--space-6)",
      borderBottom: "1px solid var(--divider)"
    }
  }, icon ? /*#__PURE__*/React.createElement("span", {
    style: {
      width: 38,
      height: 38,
      flexShrink: 0,
      borderRadius: "var(--radius-sm)",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      background: toneColor.bg,
      color: toneColor.fg
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon,
    size: 20
  })) : null, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontSize: "var(--text-lg)",
      fontWeight: "var(--weight-semibold)"
    }
  }, title), subtitle ? /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: "var(--text-sm)",
      color: "var(--text-muted)",
      marginTop: 2
    }
  }, subtitle) : null), onClose ? /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onClose,
    "aria-label": "Close",
    style: {
      background: "transparent",
      border: "none",
      color: "var(--text-faint)",
      cursor: "pointer",
      padding: 4,
      marginTop: -2
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "x",
    size: 18
  })) : null), children ? /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "var(--space-6)",
      fontSize: "var(--text-base)",
      color: "var(--text-body)"
    }
  }, children) : null, footer ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "flex-end",
      gap: "var(--space-2)",
      padding: "var(--space-4) var(--space-6)",
      background: "var(--surface-sunken)",
      borderTop: "1px solid var(--divider)"
    }
  }, footer) : null));
}
Object.assign(__ds_scope, { Modal });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Modal.jsx", error: String((e && e.message) || e) }); }

// components/feedback/MoneyConfirm.jsx
try { (() => {
/**
 * MoneyConfirm — the deliberate, auditable confirmation panel for money
 * actions (approve/deny payout holds, dispatch funds). Notably MORE
 * cautious than marketing surfaces: it restates the exact amount +
 * destination, surfaces the reason held and an audit trail, and gates
 * the confirm behind a typed match or explicit checkbox.
 *
 * rows: [{ label, value, mono }]  — the money facts.
 * audit: [{ actor, action, at }] — the trail.
 */
function MoneyConfirm({
  intent = "approve",
  // approve | deny | dispatch
  amount,
  destinationLabel = "Destination",
  destination,
  rows = [],
  reasonHeld,
  audit = [],
  confirmWord,
  // require typing this to enable
  acknowledgement,
  // checkbox label (alternative gate)
  onConfirm,
  onCancel,
  style = {}
}) {
  const [typed, setTyped] = React.useState("");
  const [ack, setAck] = React.useState(false);
  const danger = intent === "deny";
  const tone = danger ? "danger" : "positive";
  const toneSolid = danger ? "var(--status-danger-solid)" : "var(--status-positive-solid)";
  const toneBg = danger ? "var(--status-danger-bg)" : "var(--status-positive-bg)";
  const toneFg = danger ? "var(--status-danger-fg)" : "var(--status-positive-fg)";
  const gateOk = (confirmWord ? typed.trim().toUpperCase() === confirmWord.toUpperCase() : true) && (acknowledgement ? ack : true);
  const verb = intent === "deny" ? "Deny payout" : intent === "dispatch" ? "Dispatch funds" : "Approve payout";
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width: "100%",
      maxWidth: 460,
      background: "var(--surface-card)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-lg)",
      boxShadow: "var(--shadow-xl)",
      overflow: "hidden",
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 12,
      padding: "var(--space-5) var(--space-6)",
      borderBottom: "1px solid var(--divider)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 40,
      height: 40,
      borderRadius: "var(--radius-sm)",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      background: toneBg,
      color: toneFg
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: danger ? "ban" : "shield-check",
    size: 21
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontSize: "var(--text-lg)",
      fontWeight: "var(--weight-semibold)"
    }
  }, verb), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: "var(--text-xs)",
      color: "var(--text-muted)",
      display: "inline-flex",
      alignItems: "center",
      gap: 4,
      marginTop: 2
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "lock",
    size: 12
  }), " Secured money action \xB7 logged to audit trail"))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "var(--space-6)",
      display: "flex",
      flexDirection: "column",
      gap: "var(--space-5)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: "center",
      padding: "var(--space-4)",
      background: "var(--surface-sunken)",
      borderRadius: "var(--radius-md)",
      border: "1px solid var(--border-default)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "var(--text-xs)",
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-wider)",
      color: "var(--text-muted)",
      marginBottom: 4
    }
  }, "Amount"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "var(--text-3xl)",
      fontWeight: "var(--weight-bold)",
      color: "var(--text-strong)",
      fontVariantNumeric: "tabular-nums lining-nums"
    }
  }, amount)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 0,
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-md)",
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement(FactRow, {
    label: destinationLabel,
    value: destination,
    mono: true,
    first: true
  }), rows.map((r, i) => /*#__PURE__*/React.createElement(FactRow, {
    key: i,
    label: r.label,
    value: r.value,
    mono: r.mono
  }))), reasonHeld ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 10,
      padding: "var(--space-3) var(--space-4)",
      background: "var(--status-warning-bg)",
      borderRadius: "var(--radius-sm)"
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "alert-triangle",
    size: 16,
    style: {
      color: "var(--status-warning-fg)",
      flexShrink: 0,
      marginTop: 1
    }
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "var(--text-xs)",
      fontWeight: "var(--weight-semibold)",
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-wide)",
      color: "var(--status-warning-fg)",
      marginBottom: 2
    }
  }, "Reason held"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "var(--text-sm)",
      color: "var(--text-body)"
    }
  }, reasonHeld))) : null, audit.length ? /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "var(--text-xs)",
      fontWeight: "var(--weight-semibold)",
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-wide)",
      color: "var(--text-muted)",
      marginBottom: 8
    }
  }, "Audit trail"), /*#__PURE__*/React.createElement("ol", {
    style: {
      listStyle: "none",
      margin: 0,
      padding: 0,
      display: "flex",
      flexDirection: "column",
      gap: 8
    }
  }, audit.map((a, i) => /*#__PURE__*/React.createElement("li", {
    key: i,
    style: {
      display: "flex",
      gap: 9,
      alignItems: "flex-start",
      fontSize: "var(--text-sm)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 7,
      height: 7,
      borderRadius: "50%",
      background: "var(--border-strong)",
      marginTop: 6,
      flexShrink: 0
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-body)"
    }
  }, /*#__PURE__*/React.createElement("strong", {
    style: {
      color: "var(--text-strong)",
      fontWeight: "var(--weight-semibold)"
    }
  }, a.actor), " ", a.action), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "var(--text-xs)",
      color: "var(--text-faint)",
      fontFamily: "var(--font-mono)"
    }
  }, a.at)))))) : null, confirmWord ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: "var(--text-sm)",
      color: "var(--text-body)"
    }
  }, "Type ", /*#__PURE__*/React.createElement("strong", {
    style: {
      fontFamily: "var(--font-mono)",
      color: toneSolid
    }
  }, confirmWord), " to confirm"), /*#__PURE__*/React.createElement("input", {
    value: typed,
    onChange: e => setTyped(e.target.value),
    placeholder: confirmWord,
    style: {
      width: "100%",
      padding: "9px 13px",
      fontFamily: "var(--font-mono)",
      fontSize: "var(--text-base)",
      color: "var(--text-strong)",
      background: "var(--surface-card)",
      border: `1px solid ${gateOk ? toneSolid : "var(--border-strong)"}`,
      borderRadius: "var(--radius-sm)",
      outline: "none"
    }
  })) : null, acknowledgement ? /*#__PURE__*/React.createElement("label", {
    style: {
      display: "flex",
      gap: 9,
      alignItems: "flex-start",
      cursor: "pointer"
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: ack,
    onChange: e => setAck(e.target.checked),
    style: {
      marginTop: 3,
      accentColor: toneSolid
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "var(--text-sm)",
      color: "var(--text-body)"
    }
  }, acknowledgement)) : null), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "flex-end",
      gap: "var(--space-2)",
      padding: "var(--space-4) var(--space-6)",
      background: "var(--surface-sunken)",
      borderTop: "1px solid var(--divider)"
    }
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onCancel,
    style: {
      padding: "9px 16px",
      fontSize: "var(--text-base)",
      fontWeight: "var(--weight-semibold)",
      color: "var(--text-body)",
      background: "var(--surface-card)",
      border: "1px solid var(--border-strong)",
      borderRadius: "var(--radius-sm)",
      cursor: "pointer"
    }
  }, "Cancel"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    disabled: !gateOk,
    onClick: gateOk ? onConfirm : undefined,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 7,
      padding: "9px 18px",
      fontSize: "var(--text-base)",
      fontWeight: "var(--weight-semibold)",
      color: "#fff",
      background: toneSolid,
      border: "1px solid transparent",
      borderRadius: "var(--radius-sm)",
      cursor: gateOk ? "pointer" : "not-allowed",
      opacity: gateOk ? 1 : 0.5
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: danger ? "ban" : "check",
    size: 16,
    strokeWidth: 2.5
  }), " ", verb)));
}
function FactRow({
  label,
  value,
  mono,
  first
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      gap: "var(--space-4)",
      padding: "11px var(--space-4)",
      borderTop: first ? "none" : "1px solid var(--divider)",
      background: "var(--surface-card)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "var(--text-sm)",
      color: "var(--text-muted)"
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "var(--text-sm)",
      fontWeight: "var(--weight-medium)",
      color: "var(--text-strong)",
      fontFamily: mono ? "var(--font-mono)" : "inherit",
      textAlign: "right",
      wordBreak: mono ? "break-all" : "normal"
    }
  }, value));
}
Object.assign(__ds_scope, { MoneyConfirm });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/MoneyConfirm.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Toast.jsx
try { (() => {
/** Toast — transient confirmation/alert. Render a stack of these in a fixed corner. */
const TONES = {
  success: {
    icon: "check-circle",
    fg: "var(--status-positive-fg)",
    bar: "var(--status-positive-solid)"
  },
  error: {
    icon: "alert-triangle",
    fg: "var(--status-danger-fg)",
    bar: "var(--status-danger-solid)"
  },
  warning: {
    icon: "alert-triangle",
    fg: "var(--status-warning-fg)",
    bar: "var(--status-warning-solid)"
  },
  info: {
    icon: "bell",
    fg: "var(--status-info-fg)",
    bar: "var(--status-info-solid)"
  }
};
function Toast({
  tone = "info",
  title,
  message,
  onClose,
  style = {}
}) {
  const t = TONES[tone] || TONES.info;
  return /*#__PURE__*/React.createElement("div", {
    role: "status",
    style: {
      display: "flex",
      alignItems: "flex-start",
      gap: 11,
      width: 360,
      maxWidth: "calc(100vw - 32px)",
      padding: "13px 14px",
      background: "var(--surface-card)",
      border: "1px solid var(--border-default)",
      borderLeft: `3px solid ${t.bar}`,
      borderRadius: "var(--radius-md)",
      boxShadow: "var(--shadow-lg)",
      ...style
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: t.icon,
    size: 18,
    style: {
      color: t.fg,
      flexShrink: 0,
      marginTop: 1
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, title ? /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "var(--text-sm)",
      fontWeight: "var(--weight-semibold)",
      color: "var(--text-strong)"
    }
  }, title) : null, message ? /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "var(--text-sm)",
      color: "var(--text-muted)",
      marginTop: title ? 2 : 0
    }
  }, message) : null), onClose ? /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onClose,
    "aria-label": "Dismiss",
    style: {
      background: "transparent",
      border: "none",
      color: "var(--text-faint)",
      cursor: "pointer",
      padding: 2,
      marginTop: -1
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "x",
    size: 15
  })) : null);
}

/** ToastViewport — fixed stacking container for toasts. */
function ToastViewport({
  position = "bottom-right",
  children,
  style = {}
}) {
  const pos = {
    "bottom-right": {
      bottom: 20,
      right: 20,
      alignItems: "flex-end"
    },
    "bottom-left": {
      bottom: 20,
      left: 20,
      alignItems: "flex-start"
    },
    "top-right": {
      top: 20,
      right: 20,
      alignItems: "flex-end"
    },
    "top-left": {
      top: 20,
      left: 20,
      alignItems: "flex-start"
    }
  }[position];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "fixed",
      zIndex: 70,
      display: "flex",
      flexDirection: "column",
      gap: 10,
      ...pos,
      ...style
    }
  }, children);
}
Object.assign(__ds_scope, { Toast, ToastViewport });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Toast.jsx", error: String((e && e.message) || e) }); }

// components/forms/Checkbox.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Checkbox — controlled box + label, used in tables (select rows) and forms. */
function Checkbox({
  label,
  checked = false,
  onChange,
  disabled = false,
  size = "md",
  id,
  style = {},
  ...rest
}) {
  const box = size === "sm" ? 16 : 18;
  const fid = id || (label ? `nx-cb-${label.replace(/\s+/g, "-").toLowerCase()}` : undefined);
  return /*#__PURE__*/React.createElement("label", {
    htmlFor: fid,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 8,
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.55 : 1,
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    onClick: () => !disabled && onChange && onChange(!checked),
    style: {
      width: box,
      height: box,
      flexShrink: 0,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      borderRadius: "var(--radius-xs)",
      background: checked ? "var(--brand-primary)" : "var(--surface-card)",
      border: `1.5px solid ${checked ? "var(--brand-primary)" : "var(--border-strong)"}`,
      transition: "background .12s, border-color .12s"
    }
  }, checked ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "check",
    size: box - 6,
    strokeWidth: 3,
    style: {
      color: "var(--brand-primary-fg)"
    }
  }) : null), /*#__PURE__*/React.createElement("input", _extends({
    type: "checkbox",
    id: fid,
    checked: checked,
    onChange: e => onChange && onChange(e.target.checked),
    disabled: disabled,
    style: {
      position: "absolute",
      opacity: 0,
      width: 0,
      height: 0
    }
  }, rest)), label ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "var(--text-sm)",
      color: "var(--text-body)"
    }
  }, label) : null);
}
Object.assign(__ds_scope, { Checkbox });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Checkbox.jsx", error: String((e && e.message) || e) }); }

// components/forms/Input.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Input — text field with optional label, leading icon, hint and error. */
function Input({
  label,
  hint,
  error,
  icon,
  size = "md",
  id,
  style = {},
  wrapStyle = {},
  ...rest
}) {
  const [focus, setFocus] = React.useState(false);
  const fid = id || (label ? `nx-${label.replace(/\s+/g, "-").toLowerCase()}` : undefined);
  const pad = size === "sm" ? "7px 11px" : "9px 13px";
  const fs = size === "sm" ? "var(--text-sm)" : "var(--text-base)";
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 6,
      ...wrapStyle
    }
  }, label ? /*#__PURE__*/React.createElement("label", {
    htmlFor: fid,
    style: {
      fontSize: "var(--text-sm)",
      fontWeight: "var(--weight-medium)",
      color: "var(--text-body)"
    }
  }, label) : null, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      display: "flex",
      alignItems: "center"
    }
  }, icon ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon,
    size: 16,
    style: {
      position: "absolute",
      left: 11,
      color: "var(--text-faint)",
      pointerEvents: "none"
    }
  }) : null, /*#__PURE__*/React.createElement("input", _extends({
    id: fid,
    onFocus: () => setFocus(true),
    onBlur: () => setFocus(false),
    style: {
      width: "100%",
      padding: pad,
      paddingLeft: icon ? 34 : undefined,
      fontFamily: "var(--font-sans)",
      fontSize: fs,
      color: "var(--text-strong)",
      background: "var(--surface-card)",
      border: `1px solid ${error ? "var(--status-danger-solid)" : focus ? "var(--brand-primary)" : "var(--border-strong)"}`,
      borderRadius: "var(--radius-sm)",
      outline: "none",
      boxShadow: focus ? `0 0 0 var(--ring-width) color-mix(in srgb, ${error ? "var(--status-danger-solid)" : "var(--brand-primary)"} var(--ring-alpha), transparent)` : "none",
      transition: "border-color .15s, box-shadow .15s",
      ...style
    }
  }, rest))), error ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "var(--text-xs)",
      color: "var(--status-danger-fg)"
    }
  }, error) : hint ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "var(--text-xs)",
      color: "var(--text-muted)"
    }
  }, hint) : null);
}
Object.assign(__ds_scope, { Input });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Input.jsx", error: String((e && e.message) || e) }); }

// components/forms/Select.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Select — native dropdown styled to match Input, with a custom chevron. */
function Select({
  label,
  hint,
  options = [],
  size = "md",
  id,
  value,
  onChange,
  style = {},
  wrapStyle = {},
  children,
  ...rest
}) {
  const [focus, setFocus] = React.useState(false);
  const fid = id || (label ? `nx-${label.replace(/\s+/g, "-").toLowerCase()}` : undefined);
  const pad = size === "sm" ? "7px 32px 7px 11px" : "9px 34px 9px 13px";
  const fs = size === "sm" ? "var(--text-sm)" : "var(--text-base)";
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 6,
      ...wrapStyle
    }
  }, label ? /*#__PURE__*/React.createElement("label", {
    htmlFor: fid,
    style: {
      fontSize: "var(--text-sm)",
      fontWeight: "var(--weight-medium)",
      color: "var(--text-body)"
    }
  }, label) : null, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      display: "flex",
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("select", _extends({
    id: fid,
    value: value,
    onChange: onChange,
    onFocus: () => setFocus(true),
    onBlur: () => setFocus(false),
    style: {
      width: "100%",
      padding: pad,
      appearance: "none",
      WebkitAppearance: "none",
      fontFamily: "var(--font-sans)",
      fontSize: fs,
      color: "var(--text-strong)",
      background: "var(--surface-card)",
      border: `1px solid ${focus ? "var(--brand-primary)" : "var(--border-strong)"}`,
      borderRadius: "var(--radius-sm)",
      outline: "none",
      cursor: "pointer",
      boxShadow: focus ? "0 0 0 var(--ring-width) color-mix(in srgb, var(--brand-primary) var(--ring-alpha), transparent)" : "none",
      transition: "border-color .15s, box-shadow .15s",
      ...style
    }
  }, rest), children || options.map(o => {
    const val = typeof o === "object" ? o.value : o;
    const lab = typeof o === "object" ? o.label : o;
    return /*#__PURE__*/React.createElement("option", {
      key: val,
      value: val
    }, lab);
  })), /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "chevron-down",
    size: 16,
    style: {
      position: "absolute",
      right: 11,
      color: "var(--text-faint)",
      pointerEvents: "none"
    }
  })), hint ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "var(--text-xs)",
      color: "var(--text-muted)"
    }
  }, hint) : null);
}
Object.assign(__ds_scope, { Select });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Select.jsx", error: String((e && e.message) || e) }); }

// components/navigation/Sidebar.jsx
try { (() => {
/**
 * Sidebar — the dark app rail (advertiser / affiliate / operator).
 * Brand lockup at top, role chip, nav items with active state, footer
 * slot for logout. Active item uses a subtle brand-tinted fill so it
 * re-skins per tenant. items: { icon, label, href, active, badge }.
 */
function Sidebar({
  brandName = "Nexora",
  logo,
  role,
  items = [],
  footer,
  active,
  onNavigate,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("aside", {
    style: {
      width: "var(--sidebar-width)",
      flexShrink: 0,
      height: "100%",
      background: "var(--surface-inverse)",
      display: "flex",
      flexDirection: "column",
      color: "#cbd5e1",
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 10,
      height: "var(--topbar-height)",
      padding: "0 var(--space-5)",
      borderBottom: "1px solid rgba(255,255,255,.08)"
    }
  }, logo ? /*#__PURE__*/React.createElement("img", {
    src: logo,
    alt: brandName,
    style: {
      height: 26,
      width: "auto"
    }
  }) : /*#__PURE__*/React.createElement("span", {
    style: {
      width: 28,
      height: 28,
      borderRadius: 7,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      background: "var(--brand-primary)",
      color: "var(--brand-primary-fg)",
      fontWeight: 700,
      fontSize: 15
    }
  }, brandName[0]), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "#fff",
      fontWeight: "var(--weight-semibold)",
      fontSize: "var(--text-lg)",
      letterSpacing: "-0.01em"
    }
  }, brandName)), role ? /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "var(--space-4) var(--space-5)",
      borderBottom: "1px solid rgba(255,255,255,.08)"
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: "var(--text-xs)",
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-wider)",
      color: "#64748b",
      marginBottom: 4
    }
  }, role.kind || "Account"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: "var(--text-sm)",
      color: "#fff",
      fontWeight: "var(--weight-medium)",
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis"
    }
  }, role.name)) : null, /*#__PURE__*/React.createElement("nav", {
    style: {
      flex: 1,
      overflowY: "auto",
      padding: "var(--space-3)",
      display: "flex",
      flexDirection: "column",
      gap: 2
    }
  }, items.map(it => /*#__PURE__*/React.createElement(NavItem, {
    key: it.label,
    item: it,
    active: active === it.label || it.active,
    onNavigate: onNavigate
  }))), footer ? /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "var(--space-3)",
      borderTop: "1px solid rgba(255,255,255,.08)"
    }
  }, footer) : null);
}
function NavItem({
  item,
  active,
  onNavigate
}) {
  const [hover, setHover] = React.useState(false);
  return /*#__PURE__*/React.createElement("a", {
    href: item.href || "#",
    onClick: onNavigate ? e => {
      e.preventDefault();
      onNavigate(item);
    } : undefined,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      display: "flex",
      alignItems: "center",
      gap: 12,
      padding: "9px 12px",
      borderRadius: "var(--radius-sm)",
      textDecoration: "none",
      fontSize: "var(--text-base)",
      fontWeight: "var(--weight-medium)",
      color: active ? "#fff" : hover ? "#fff" : "#cbd5e1",
      background: active ? "var(--brand-primary)" : hover ? "rgba(255,255,255,.07)" : "transparent",
      transition: "background .12s, color .12s"
    }
  }, item.icon ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: item.icon,
    size: 18
  }) : null, /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1
    }
  }, item.label), item.badge != null ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "var(--text-xs)",
      fontWeight: 600,
      padding: "1px 7px",
      borderRadius: "var(--radius-full)",
      background: active ? "rgba(255,255,255,.25)" : "var(--brand-primary)",
      color: "#fff"
    }
  }, item.badge) : null);
}
Object.assign(__ds_scope, { Sidebar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/Sidebar.jsx", error: String((e && e.message) || e) }); }

// components/navigation/Topbar.jsx
try { (() => {
/**
 * Topbar — light header above the content area. Page title on the left,
 * utility actions (search, theme, notifications, user) on the right.
 */
function Topbar({
  title,
  subtitle,
  actions,
  user,
  onToggleTheme,
  theme = "light",
  style = {}
}) {
  return /*#__PURE__*/React.createElement("header", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "var(--space-4)",
      height: "var(--topbar-height)",
      padding: "0 var(--space-6)",
      flexShrink: 0,
      background: "var(--surface-card)",
      borderBottom: "1px solid var(--border-default)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("h1", {
    style: {
      fontSize: "var(--text-xl)",
      fontWeight: "var(--weight-semibold)",
      lineHeight: 1.2,
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis"
    }
  }, title), subtitle ? /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: "var(--text-sm)",
      color: "var(--text-muted)"
    }
  }, subtitle) : null), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      display: "flex",
      alignItems: "center",
      gap: "var(--space-2)"
    }
  }, actions, onToggleTheme ? /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onToggleTheme,
    "aria-label": "Toggle theme",
    style: iconBtn
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: theme === "dark" ? "sun" : "moon",
    size: 18
  })) : null, user ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 9,
      paddingLeft: "var(--space-2)"
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Avatar, {
    name: user.name,
    src: user.avatar,
    size: "sm"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      lineHeight: 1.2
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "var(--text-sm)",
      fontWeight: "var(--weight-medium)",
      color: "var(--text-strong)"
    }
  }, user.name), user.meta ? /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "var(--text-xs)",
      color: "var(--text-muted)"
    }
  }, user.meta) : null)) : null));
}
const iconBtn = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: 38,
  height: 38,
  borderRadius: "var(--radius-sm)",
  background: "transparent",
  border: "1px solid transparent",
  color: "var(--text-muted)",
  cursor: "pointer"
};
Object.assign(__ds_scope, { Topbar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/Topbar.jsx", error: String((e && e.message) || e) }); }

// ui_kits/advertiser/screens.jsx
try { (() => {
/* Nexora — Advertiser portal: offer management (list + create with targeting
   & revenue model) and conversions. Composes the bundle. window.AdvertiserScreens. */
(function () {
  const NX = window.NexoraDesignSystem_985ae7;
  const {
    DataTable,
    StatusPill,
    Badge,
    Card,
    CardHeader,
    Button,
    Input,
    Select,
    FilterBar,
    Modal,
    EmptyState,
    Icon,
    StatTile
  } = NX;
  const money = n => "$" + n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
  const offers = [{
    id: 1,
    title: "Crypto Wallet Signup",
    model: "CPA",
    status: "Approved",
    geo: "KE · NG · ZA",
    payout: 14.5,
    clicks: 18240,
    conv: 412,
    rev: 5974
  }, {
    id: 2,
    title: "Neobank Account CPL",
    model: "CPL",
    status: "Approved",
    geo: "NG",
    payout: 9.0,
    clicks: 9120,
    conv: 318,
    rev: 2862
  }, {
    id: 3,
    title: "Forex Broker Deposit",
    model: "CPA",
    status: "Pending",
    geo: "ZA · KE",
    payout: 120.0,
    clicks: 2210,
    conv: 96,
    rev: 11520
  }, {
    id: 4,
    title: "Sports Betting FTD",
    model: "CPA",
    status: "Held",
    geo: "KE · TZ",
    payout: 38.0,
    clicks: 4400,
    conv: 54,
    rev: 2052
  }, {
    id: 5,
    title: "VPN Annual Plan",
    model: "RevShare",
    status: "Dormant",
    geo: "Global",
    payout: 22.0,
    clicks: 760,
    conv: 12,
    rev: 264
  }];
  const modelTone = {
    CPA: "brand",
    CPL: "info",
    RevShare: "positive"
  };
  function Offers({
    onCreate
  }) {
    const [status, setStatus] = React.useState("All");
    const rows = status === "All" ? offers : offers.filter(o => o.status === status);
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        gap: 18
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "grid",
        gridTemplateColumns: "repeat(4,1fr)",
        gap: 16
      }
    }, /*#__PURE__*/React.createElement(StatTile, {
      label: "Live offers",
      value: "4",
      icon: "tag"
    }), /*#__PURE__*/React.createElement(StatTile, {
      label: "Clicks (30d)",
      value: "34,730",
      icon: "mouse-pointer-click",
      delta: "8.2%"
    }), /*#__PURE__*/React.createElement(StatTile, {
      label: "Conversions (30d)",
      value: "892",
      icon: "target",
      delta: "2.4%"
    }), /*#__PURE__*/React.createElement(StatTile, {
      label: "Approved revenue",
      value: "$22,672",
      icon: "dollar-sign",
      accent: true,
      delta: "5.0%"
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 6
      }
    }, ["All", "Approved", "Pending", "Held", "Dormant"].map(s => /*#__PURE__*/React.createElement("button", {
      key: s,
      onClick: () => setStatus(s),
      style: {
        padding: "6px 13px",
        borderRadius: 999,
        fontSize: 13,
        fontWeight: 500,
        cursor: "pointer",
        border: `1px solid ${status === s ? "var(--brand-primary)" : "var(--border-strong)"}`,
        background: status === s ? "var(--brand-tint)" : "var(--surface-card)",
        color: status === s ? "var(--brand-tint-fg)" : "var(--text-muted)"
      }
    }, s))), /*#__PURE__*/React.createElement(Button, {
      iconLeft: "plus",
      onClick: onCreate
    }, "Create offer")), /*#__PURE__*/React.createElement(Card, {
      padding: "none"
    }, rows.length === 0 ? /*#__PURE__*/React.createElement(EmptyState, {
      icon: "tag",
      title: "No offers in this status",
      compact: true
    }) : /*#__PURE__*/React.createElement(DataTable, {
      rowKey: "id",
      dense: true,
      style: {
        border: "none",
        borderRadius: 0
      },
      columns: [{
        key: "title",
        header: "Offer",
        sortable: true,
        render: (v, r) => /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
          style: {
            fontWeight: 600,
            color: "var(--text-strong)"
          }
        }, v), /*#__PURE__*/React.createElement("div", {
          style: {
            fontSize: 12,
            color: "var(--text-muted)",
            display: "flex",
            alignItems: "center",
            gap: 4
          }
        }, /*#__PURE__*/React.createElement(Icon, {
          name: "globe",
          size: 12
        }), r.geo))
      }, {
        key: "model",
        header: "Model",
        render: v => /*#__PURE__*/React.createElement(Badge, {
          tone: modelTone[v]
        }, v)
      }, {
        key: "status",
        header: "Status",
        render: v => /*#__PURE__*/React.createElement(StatusPill, {
          status: v,
          size: "sm"
        })
      }, {
        key: "clicks",
        header: "Clicks",
        align: "right",
        mono: true,
        sortable: true,
        render: v => v.toLocaleString()
      }, {
        key: "conv",
        header: "Conv.",
        align: "right",
        mono: true,
        sortable: true
      }, {
        key: "payout",
        header: "Payout",
        align: "right",
        mono: true,
        render: v => money(v)
      }, {
        key: "rev",
        header: "Revenue",
        align: "right",
        mono: true,
        sortable: true,
        render: v => money(v)
      }, {
        key: "_a",
        header: "",
        align: "right",
        render: () => /*#__PURE__*/React.createElement(Button, {
          size: "sm",
          variant: "ghost",
          iconLeft: "settings"
        }, "Edit")
      }],
      rows: rows
    })));
  }

  /* Create-offer form (rich, in a wide modal) */
  function CreateOffer({
    onClose
  }) {
    const [model, setModel] = React.useState("CPA");
    return /*#__PURE__*/React.createElement(Modal, {
      title: "Create offer",
      subtitle: "Define targeting, payout and revenue model",
      icon: "tag",
      width: 620,
      onClose: onClose,
      footer: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Button, {
        variant: "secondary",
        onClick: onClose
      }, "Cancel"), /*#__PURE__*/React.createElement(Button, {
        iconLeft: "check",
        onClick: onClose
      }, "Create offer"))
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        gap: 16
      }
    }, /*#__PURE__*/React.createElement(Input, {
      label: "Offer title",
      placeholder: "Crypto Wallet Signup"
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 14
      }
    }, /*#__PURE__*/React.createElement(Select, {
      label: "Category",
      options: ["Crypto", "Finance", "iGaming", "Software", "Education"]
    }), /*#__PURE__*/React.createElement(Select, {
      label: "Revenue model",
      value: model,
      onChange: e => setModel(e.target.value),
      options: ["CPA", "CPL", "RevShare"]
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 14
      }
    }, /*#__PURE__*/React.createElement(Input, {
      label: model === "RevShare" ? "Revenue share %" : "Payout (USD)",
      defaultValue: model === "RevShare" ? "30" : "14.50",
      icon: model === "RevShare" ? "trending-up" : "dollar-sign"
    }), /*#__PURE__*/React.createElement(Select, {
      label: "Currency",
      options: ["USD", "EUR", "KES", "NGN", "ZAR"]
    })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
      style: {
        fontSize: 13,
        fontWeight: 500,
        color: "var(--text-body)",
        display: "block",
        marginBottom: 8
      }
    }, "Geo targeting"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexWrap: "wrap",
        gap: 8
      }
    }, ["Kenya", "Nigeria", "South Africa", "Tanzania", "Uganda", "Egypt", "Global"].map(c => /*#__PURE__*/React.createElement(GeoChip, {
      key: c
    }, c)))), /*#__PURE__*/React.createElement(Input, {
      label: "Destination URL",
      icon: "link",
      placeholder: "https://advertiser.com/lp?click={click_id}"
    }), /*#__PURE__*/React.createElement(Input, {
      label: "Daily cap (conversions)",
      defaultValue: "500",
      hint: "Leave blank for uncapped"
    })));
  }
  function GeoChip({
    children
  }) {
    const [on, setOn] = React.useState(["Kenya", "Nigeria"].includes(children));
    return /*#__PURE__*/React.createElement("button", {
      type: "button",
      onClick: () => setOn(!on),
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "6px 12px",
        borderRadius: 999,
        fontSize: 13,
        cursor: "pointer",
        border: `1px solid ${on ? "var(--brand-primary)" : "var(--border-strong)"}`,
        background: on ? "var(--brand-tint)" : "var(--surface-card)",
        color: on ? "var(--brand-tint-fg)" : "var(--text-muted)"
      }
    }, on && /*#__PURE__*/React.createElement(Icon, {
      name: "check",
      size: 12
    }), children);
  }
  window.AdvertiserScreens = {
    Offers,
    CreateOffer
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/advertiser/screens.jsx", error: String((e && e.message) || e) }); }

// ui_kits/affiliate/screens.jsx
try { (() => {
/* Nexora — Affiliate portal screens. Composes the design-system bundle
   (window.NexoraDesignSystem_985ae7). Exposes screens on window for index.html. */
(function () {
  const NX = window.NexoraDesignSystem_985ae7;
  const {
    Sidebar,
    Topbar,
    StatTile,
    DataTable,
    StatusPill,
    Badge,
    Card,
    CardHeader,
    Button,
    Input,
    Select,
    FilterBar,
    Modal,
    EmptyState,
    Avatar,
    Icon
  } = NX;
  const money = n => "$" + n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });

  /* ---- Small SVG performance chart (clicks vs conversions) ---- */
  function MiniChart({
    data,
    height = 150
  }) {
    const gid = React.useMemo(() => "nxg-" + Math.random().toString(36).slice(2, 8), []);
    const w = 720,
      h = height,
      pad = 8;
    const max = Math.max(...data.map(d => d.clicks)) * 1.15;
    const stepX = (w - pad * 2) / (data.length - 1);
    const y = v => h - pad - v / max * (h - pad * 2);
    const path = key => data.map((d, i) => `${i ? "L" : "M"}${pad + i * stepX},${y(d[key])}`).join(" ");
    const area = path("clicks") + ` L${pad + (data.length - 1) * stepX},${h - pad} L${pad},${h - pad} Z`;
    return /*#__PURE__*/React.createElement("svg", {
      viewBox: `0 0 ${w} ${h}`,
      width: "100%",
      height: height,
      preserveAspectRatio: "none",
      style: {
        display: "block"
      }
    }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
      id: gid,
      x1: "0",
      y1: "0",
      x2: "0",
      y2: "1"
    }, /*#__PURE__*/React.createElement("stop", {
      offset: "0%",
      stopColor: "var(--brand-primary)",
      stopOpacity: "0.22"
    }), /*#__PURE__*/React.createElement("stop", {
      offset: "100%",
      stopColor: "var(--brand-primary)",
      stopOpacity: "0"
    }))), /*#__PURE__*/React.createElement("path", {
      d: area,
      fill: `url(#${gid})`
    }), /*#__PURE__*/React.createElement("path", {
      d: path("clicks"),
      fill: "none",
      stroke: "var(--brand-primary)",
      strokeWidth: "2.5",
      strokeLinejoin: "round"
    }), /*#__PURE__*/React.createElement("path", {
      d: path("conv"),
      fill: "none",
      stroke: "var(--text-faint)",
      strokeWidth: "2",
      strokeDasharray: "4 4",
      strokeLinejoin: "round"
    }));
  }

  /* ---------- LOGIN ---------- */
  // Energy presets reshape the brand-side analytics: motion speed, whether
  // loops run, and how "live" the numbers feel.
  const ENERGY = {
    calm: {
      spd: 1.7,
      loop: false,
      tickMs: 0,
      label: "Calm"
    },
    live: {
      spd: 1.0,
      loop: true,
      tickMs: 2600,
      label: "Live"
    },
    high: {
      spd: 0.5,
      loop: true,
      tickMs: 900,
      label: "Trading floor"
    }
  };
  function prefersReduced() {
    return typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  // Count up to a target, then (if live) keep ticking upward to feel real-time.
  function useLiveNumber(target, {
    animate,
    tickMs
  }) {
    const [val, setVal] = React.useState(animate ? 0 : target);
    React.useEffect(() => {
      if (!animate) {
        setVal(target);
        return;
      }
      let raf, start;
      const dur = 1100;
      const step = t => {
        if (!start) start = t;
        const p = Math.min(1, (t - start) / dur);
        const eased = 1 - Math.pow(1 - p, 3);
        setVal(target * eased);
        if (p < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
      let iv;
      if (tickMs) iv = setInterval(() => setVal(v => v + Math.random() * 6.5 + 0.5), tickMs);
      return () => {
        cancelAnimationFrame(raf);
        if (iv) clearInterval(iv);
      };
    }, [target, animate, tickMs]);
    return val;
  }

  // Animated fintech analytics panel — self-drawing equity curve, a live
  // earnings ticker, breathing volume bars and drifting metric chips.
  function AnalyticsHero({
    energy
  }) {
    const cfg = ENERGY[energy] || ENERGY.live;
    const animate = cfg.loop && !prefersReduced();
    const drawOnce = !prefersReduced();
    const spd = cfg.spd;
    const earnings = useLiveNumber(8420, {
      animate,
      tickMs: cfg.tickMs
    });
    const convRate = useLiveNumber(2.14, {
      animate,
      tickMs: 0
    });
    const pts = [22, 30, 26, 38, 34, 48, 44, 60, 56, 72, 68, 86];
    const w = 300,
      h = 96,
      max = 96,
      sx = w / (pts.length - 1);
    const y = v => h - v / max * (h - 8) - 4;
    const line = pts.map((d, i) => (i ? "L" : "M") + (i * sx).toFixed(1) + "," + y(d).toFixed(1)).join(" ");
    const tipX = (pts.length - 1) * sx,
      tipY = y(pts[pts.length - 1]);
    return /*#__PURE__*/React.createElement("div", {
      style: {
        position: "relative",
        width: "100%",
        maxWidth: 380
      }
    }, /*#__PURE__*/React.createElement(FloatChip, {
      animate: animate,
      spd: spd,
      delay: 0,
      style: {
        top: -14,
        right: 8
      },
      icon: "trending-up",
      label: "ROI",
      value: "+218%",
      tone: "#34d399"
    }), /*#__PURE__*/React.createElement(FloatChip, {
      animate: animate,
      spd: spd,
      delay: spd * 0.6,
      style: {
        bottom: 18,
        left: -16
      },
      icon: "mouse-pointer-click",
      label: "CTR",
      value: "6.4%",
      tone: "var(--brand-primary)"
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        position: "relative",
        overflow: "hidden",
        background: "rgba(255,255,255,.04)",
        border: "1px solid rgba(255,255,255,.1)",
        borderRadius: 18,
        padding: 20,
        backdropFilter: "blur(6px)",
        boxShadow: "0 30px 60px -24px rgba(0,0,0,.6)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 12
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 8,
        color: "#9fb0d0",
        fontSize: 12,
        fontWeight: 500,
        textTransform: "uppercase",
        letterSpacing: ".08em"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 7,
        height: 7,
        borderRadius: "50%",
        background: "#34d399",
        boxShadow: "0 0 0 0 rgba(52,211,153,.6)",
        animation: animate ? `nx-pulse ${1.6 * spd}s ease-in-out infinite` : "none"
      }
    }), "Live earnings \xB7 today"), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        fontWeight: 600,
        color: "#34d399",
        background: "rgba(52,211,153,.14)",
        padding: "2px 7px",
        borderRadius: 999
      }
    }, "\u25B2 +6.1%")), /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: 34,
        fontWeight: 700,
        color: "#fff",
        lineHeight: 1,
        fontVariantNumeric: "tabular-nums",
        letterSpacing: "-0.01em"
      }
    }, "$", earnings.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        position: "relative",
        marginTop: 16
      }
    }, /*#__PURE__*/React.createElement("svg", {
      viewBox: `0 0 ${w} ${h}`,
      width: "100%",
      height: h,
      preserveAspectRatio: "none",
      style: {
        display: "block",
        overflow: "visible"
      }
    }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
      id: "nx-hero-fill",
      x1: "0",
      y1: "0",
      x2: "0",
      y2: "1"
    }, /*#__PURE__*/React.createElement("stop", {
      offset: "0%",
      stopColor: "var(--brand-primary)",
      stopOpacity: "0.34"
    }), /*#__PURE__*/React.createElement("stop", {
      offset: "100%",
      stopColor: "var(--brand-primary)",
      stopOpacity: "0"
    }))), /*#__PURE__*/React.createElement("path", {
      d: line + ` L${w},${h} L0,${h} Z`,
      fill: "url(#nx-hero-fill)",
      opacity: drawOnce ? 0 : 1,
      style: drawOnce ? {
        animation: `nx-fade ${1.1 * spd}s ease ${0.5 * spd}s forwards`
      } : undefined
    }), /*#__PURE__*/React.createElement("path", {
      d: line,
      fill: "none",
      stroke: "var(--brand-primary)",
      strokeWidth: "2.5",
      strokeLinejoin: "round",
      strokeLinecap: "round",
      strokeDasharray: drawOnce ? 1000 : undefined,
      strokeDashoffset: drawOnce ? 1000 : undefined,
      style: drawOnce ? {
        animation: `nx-draw ${1.5 * spd}s ease forwards`
      } : undefined
    }), /*#__PURE__*/React.createElement("circle", {
      cx: tipX,
      cy: tipY,
      r: "4.5",
      fill: "#fff",
      stroke: "var(--brand-primary)",
      strokeWidth: "2.5",
      style: animate ? {
        animation: `nx-tip ${1.6 * spd}s ease-in-out infinite`
      } : undefined
    })), animate && /*#__PURE__*/React.createElement("div", {
      style: {
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        background: "linear-gradient(100deg, transparent 30%, rgba(255,255,255,.14) 50%, transparent 70%)",
        animation: `nx-sweep ${3 * spd}s ease-in-out infinite`
      }
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "space-between",
        marginTop: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "flex-end",
        gap: 5,
        height: 34
      }
    }, [0.5, 0.8, 0.45, 0.95, 0.65, 0.85, 0.55].map((b, i) => /*#__PURE__*/React.createElement("span", {
      key: i,
      style: {
        width: 7,
        height: 34,
        borderRadius: 3,
        background: "var(--brand-primary)",
        opacity: 0.45 + b * 0.55,
        transformOrigin: "bottom",
        transform: `scaleY(${b})`,
        animation: animate ? `nx-bar ${(1.1 + i % 3 * 0.25) * spd}s ease-in-out ${i * 0.12 * spd}s infinite` : "none"
      }
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        textAlign: "right"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        color: "#9fb0d0",
        textTransform: "uppercase",
        letterSpacing: ".06em"
      }
    }, "Conv. rate"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: 18,
        fontWeight: 700,
        color: "#fff",
        fontVariantNumeric: "tabular-nums"
      }
    }, convRate.toFixed(2), "%")))), /*#__PURE__*/React.createElement("style", null, `
          @keyframes nx-draw { to { stroke-dashoffset: 0; } }
          @keyframes nx-fade { to { opacity: 1; } }
          @keyframes nx-sweep { 0% { transform: translateX(-120%); } 60%,100% { transform: translateX(120%); } }
          @keyframes nx-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(52,211,153,.55); } 50% { box-shadow: 0 0 0 6px rgba(52,211,153,0); } }
          @keyframes nx-tip { 0%,100% { r: 4.5; opacity: 1; } 50% { r: 6.5; opacity: .75; } }
          @keyframes nx-bar { 0%,100% { transform: scaleY(.4); } 50% { transform: scaleY(1); } }
          @keyframes nx-float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-7px); } }
        `));
  }

  // Animated candlestick (OHLC) chart — green/red bodies with wicks that
  // grow in on mount, then (when live) the latest candle breathes and a
  // fresh candle periodically shifts the series, like a trading terminal.
  function CandleChart({
    energy
  }) {
    const cfg = ENERGY[energy] || ENERGY.live;
    const animate = cfg.loop && !prefersReduced();
    const draw = !prefersReduced();
    const spd = cfg.spd;
    const SEED = [{
      o: 38,
      c: 52,
      h: 58,
      l: 34
    }, {
      o: 52,
      c: 46,
      h: 56,
      l: 42
    }, {
      o: 46,
      c: 62,
      h: 66,
      l: 44
    }, {
      o: 62,
      c: 58,
      h: 70,
      l: 54
    }, {
      o: 58,
      c: 72,
      h: 76,
      l: 56
    }, {
      o: 72,
      c: 66,
      h: 78,
      l: 62
    }, {
      o: 66,
      c: 82,
      h: 86,
      l: 64
    }, {
      o: 82,
      c: 78,
      h: 90,
      l: 74
    }, {
      o: 78,
      c: 92,
      h: 96,
      l: 76
    }];
    const [candles, setCandles] = React.useState(SEED);
    React.useEffect(() => {
      if (!animate || !cfg.tickMs) {
        setCandles(SEED);
        return;
      }
      const iv = setInterval(() => {
        setCandles(prev => {
          const last = prev[prev.length - 1];
          const o = last.c;
          const drift = (Math.random() - 0.45) * 22;
          const c = Math.max(20, Math.min(96, o + drift));
          const h = Math.min(100, Math.max(o, c) + Math.random() * 8);
          const l = Math.max(8, Math.min(o, c) - Math.random() * 8);
          return [...prev.slice(1), {
            o,
            c,
            h,
            l
          }];
        });
      }, cfg.tickMs);
      return () => clearInterval(iv);
    }, [animate, cfg.tickMs]);
    const W = 188,
      H = 120,
      n = candles.length,
      slot = W / n,
      bw = slot * 0.52;
    const y = v => H - v / 100 * (H - 6) - 3;
    return /*#__PURE__*/React.createElement("div", {
      style: {
        position: "relative",
        width: 224,
        background: "rgba(255,255,255,.04)",
        border: "1px solid rgba(255,255,255,.1)",
        borderRadius: 16,
        padding: "14px 16px 12px",
        backdropFilter: "blur(6px)",
        boxShadow: "0 24px 48px -20px rgba(0,0,0,.6)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 8
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 7,
        fontSize: 11,
        fontWeight: 600,
        color: "#9fb0d0",
        textTransform: "uppercase",
        letterSpacing: ".07em"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "bar-chart",
      size: 13,
      style: {
        color: "var(--brand-primary)"
      }
    }), " EPC \xB7 1h"), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        fontWeight: 700,
        color: "#34d399",
        fontFamily: "var(--font-mono)"
      }
    }, "\u25B2 1.42")), /*#__PURE__*/React.createElement("svg", {
      viewBox: `0 0 ${W} ${H}`,
      width: "100%",
      height: H,
      style: {
        display: "block",
        overflow: "visible"
      }
    }, [28, 56, 84].map(gy => /*#__PURE__*/React.createElement("line", {
      key: gy,
      x1: "0",
      y1: y(gy),
      x2: W,
      y2: y(gy),
      stroke: "rgba(255,255,255,.06)",
      strokeWidth: "1"
    })), candles.map((d, i) => {
      const cx = i * slot + slot / 2;
      const up = d.c >= d.o;
      const col = up ? "#34d399" : "#fb7185";
      const bodyTop = y(Math.max(d.o, d.c));
      const bodyH = Math.max(2, Math.abs(y(d.o) - y(d.c)));
      const last = i === n - 1;
      const style = animate && last ? {
        transformBox: "fill-box",
        transformOrigin: "center bottom",
        animation: `nx-candle-breathe ${1.8 * spd}s ease-in-out infinite`
      } : {};
      return /*#__PURE__*/React.createElement("g", {
        key: i,
        style: style
      }, /*#__PURE__*/React.createElement("line", {
        x1: cx,
        y1: y(d.h),
        x2: cx,
        y2: y(d.l),
        stroke: col,
        strokeWidth: "1.4"
      }), /*#__PURE__*/React.createElement("rect", {
        x: cx - bw / 2,
        y: bodyTop,
        width: bw,
        height: bodyH,
        rx: "1.5",
        fill: col,
        opacity: last ? 1 : 0.9
      }));
    })), /*#__PURE__*/React.createElement("style", null, `
          @keyframes nx-candle-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
          @keyframes nx-candle-breathe { 0%,100% { transform: scaleY(1); } 50% { transform: scaleY(1.08); } }
        `));
  }
  function FloatChip({
    icon,
    label,
    value,
    tone,
    style,
    animate,
    spd,
    delay
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        position: "absolute",
        zIndex: 2,
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 12px",
        background: "rgba(13,19,32,.92)",
        border: "1px solid rgba(255,255,255,.12)",
        borderRadius: 12,
        boxShadow: "0 16px 32px -12px rgba(0,0,0,.7)",
        animation: animate ? `nx-float ${4 * spd}s ease-in-out ${delay}s infinite` : "none",
        ...style
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 26,
        height: 26,
        borderRadius: 7,
        background: "color-mix(in srgb, " + tone + " 20%, transparent)",
        color: tone,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: icon,
      size: 15
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        lineHeight: 1.15
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 10,
        color: "#9fb0d0",
        textTransform: "uppercase",
        letterSpacing: ".06em"
      }
    }, label), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 14,
        fontWeight: 700,
        color: "#fff",
        fontFamily: "var(--font-mono)"
      }
    }, value)));
  }

  // Nexora mark — the "N" whose right leg rises into an up-trending arrow.
  // Left stroke + diagonal follow the brand color; the arrow leg is the
  // teal "growth/profit" accent (matches the real logo's blue→green).
  function NexoraMark({
    size = 34
  }) {
    return /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 32 32",
      fill: "none",
      "aria-label": "Nexora",
      role: "img",
      style: {
        display: "block",
        overflow: "visible"
      }
    }, /*#__PURE__*/React.createElement("path", {
      d: "M7.5 25.5 L7.5 7.5 L19.5 24",
      stroke: "var(--brand-primary)",
      strokeWidth: "3.6",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M19.5 24 L26 6.5",
      stroke: "#34d399",
      strokeWidth: "3.6",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M21.6 8.4 L26 6.5 L27.6 11.2",
      stroke: "#34d399",
      strokeWidth: "3.6",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }));
  }
  function Login({
    brandName,
    logo,
    onLogin,
    energy = "live"
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        minHeight: "100%",
        display: "grid",
        gridTemplateColumns: "1.32fr 0.78fr"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        position: "relative",
        overflow: "hidden",
        background: "#0d1320",
        color: "#fff",
        padding: "52px 52px",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        gap: 28,
        backgroundImage: "radial-gradient(ellipse 90% 70% at 25% 0%, color-mix(in srgb, var(--brand-primary) 32%, transparent), transparent 60%)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        position: "absolute",
        top: 64,
        right: 44,
        zIndex: 1
      }
    }, /*#__PURE__*/React.createElement(CandleChart, {
      energy: energy
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 11
      }
    }, /*#__PURE__*/React.createElement(NexoraMark, {
      size: 34
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontWeight: 600,
        fontSize: 18
      }
    }, brandName)), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        gap: 30
      }
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h1", {
      style: {
        color: "#fff",
        fontSize: 40,
        fontWeight: 600,
        letterSpacing: "-0.02em",
        lineHeight: 1.08
      }
    }, "Track. Optimize.", /*#__PURE__*/React.createElement("br", null), "Profit."), /*#__PURE__*/React.createElement("p", {
      style: {
        color: "#9fb0d0",
        fontSize: 16,
        marginTop: 14,
        maxWidth: "38ch"
      }
    }, "Promote high-converting offers, watch every click in real time, and get paid in crypto or fiat.")), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        justifyContent: "center",
        paddingRight: 8
      }
    }, /*#__PURE__*/React.createElement(AnalyticsHero, {
      energy: energy
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 22,
        color: "#9fb0d0",
        fontSize: 13
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        gap: 6,
        alignItems: "center"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "shield-check",
      size: 15
    }), " SOC-2 controls"), /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        gap: 6,
        alignItems: "center"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "zap",
      size: 15
    }), " Real-time tracking"))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "40px 36px",
        background: "var(--surface-app)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: "100%",
        maxWidth: 320
      }
    }, /*#__PURE__*/React.createElement("h2", {
      style: {
        fontSize: 22,
        fontWeight: 600,
        marginBottom: 4
      }
    }, "Affiliate sign in"), /*#__PURE__*/React.createElement("p", {
      style: {
        fontSize: 14,
        color: "var(--text-muted)",
        marginBottom: 24
      }
    }, "Welcome back to your ", brandName, " dashboard."), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        gap: 16
      }
    }, /*#__PURE__*/React.createElement(Input, {
      label: "Email",
      icon: "globe",
      defaultValue: "grace@trafficlab.io"
    }), /*#__PURE__*/React.createElement(Input, {
      label: "Password",
      type: "password",
      defaultValue: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"
    }), /*#__PURE__*/React.createElement(Button, {
      full: true,
      onClick: onLogin,
      iconRight: "arrow-right"
    }, "Sign in"), /*#__PURE__*/React.createElement("div", {
      style: {
        textAlign: "center",
        fontSize: 13,
        color: "var(--text-muted)"
      }
    }, "New here? ", /*#__PURE__*/React.createElement("a", {
      href: "#",
      onClick: e => {
        e.preventDefault();
        onLogin();
      }
    }, "Request an account"))))));
  }

  /* ---------- DASHBOARD ---------- */
  const chartData = [{
    clicks: 3200,
    conv: 70
  }, {
    clicks: 4100,
    conv: 96
  }, {
    clicks: 3800,
    conv: 88
  }, {
    clicks: 5200,
    conv: 120
  }, {
    clicks: 6100,
    conv: 142
  }, {
    clicks: 5600,
    conv: 131
  }, {
    clicks: 7400,
    conv: 168
  }, {
    clicks: 6900,
    conv: 159
  }, {
    clicks: 8200,
    conv: 190
  }];
  const recentConv = [{
    id: 1,
    time: "09:42",
    offer: "Crypto Wallet Signup",
    geo: "KE",
    status: "Approved",
    payout: 14.5
  }, {
    id: 2,
    time: "09:31",
    offer: "Neobank CPL",
    geo: "NG",
    status: "Pending",
    payout: 9.0
  }, {
    id: 3,
    time: "08:55",
    offer: "Forex Broker FTD",
    geo: "ZA",
    status: "Approved",
    payout: 120.0
  }, {
    id: 4,
    time: "08:40",
    offer: "Sports Betting FTD",
    geo: "KE",
    status: "Held",
    payout: 38.0
  }, {
    id: 5,
    time: "08:12",
    offer: "Crypto Wallet Signup",
    geo: "TZ",
    status: "Approved",
    payout: 14.5
  }];

  // Everflow-style "My Stats" metric cards: Current Month + % delta, big
  // number, sparkline, then Today / Yesterday / Last Month breakdown.
  const everflowMetrics = [{
    label: "Events",
    value: "1,284",
    pct: "12%",
    up: true,
    today: "42",
    yest: "38",
    last: "1,102",
    spark: [3, 5, 4, 6, 7, 6, 8, 9],
    money: false
  }, {
    label: "Conversions",
    value: "1,034",
    pct: "3.1%",
    up: true,
    today: "31",
    yest: "36",
    last: "972",
    spark: [5, 4, 6, 5, 7, 8, 7, 9],
    money: false
  }, {
    label: "Revenue",
    value: "$8,420.00",
    pct: "6.1%",
    up: true,
    today: "$210.00",
    yest: "$184.00",
    last: "$7,932.00",
    spark: [4, 5, 5, 6, 7, 7, 8, 9],
    money: true
  }, {
    label: "Redirect Traffic Revenue",
    value: "$1,240.00",
    pct: "0%",
    up: null,
    today: "$0.00",
    yest: "$0.00",
    last: "$1,240.00",
    spark: [5, 5, 5, 5, 5, 5, 5, 5],
    money: true
  }, {
    label: "Clicks",
    value: "48,210",
    pct: "12.4%",
    up: true,
    today: "1,204",
    yest: "1,180",
    last: "44,020",
    spark: [3, 4, 4, 5, 6, 7, 8, 9],
    money: false
  }];
  const welcomeCards = [{
    icon: "zap",
    title: "Welcome, Grace!",
    body: "Access premium offers, expert support and innovative tools to grow your affiliate earnings.",
    cta: null,
    primary: true
  }, {
    icon: "tag",
    title: "Top Offers, Real Results",
    body: "Don't waste time. Promote our highest-converting campaigns in the most profitable verticals.",
    cta: "Browse the offer sheet"
  }, {
    icon: "help-circle",
    title: "Direct Support",
    body: "Questions? Ideas? Let's talk. Our team is always just one message away.",
    cta: "Chat with us"
  }, {
    icon: "shield-check",
    title: "Complete Your KYC",
    body: "Quick and easy. Verify once to get paid fast and stay compliant.",
    cta: "Start verification"
  }];
  function Spark({
    data,
    up
  }) {
    const w = 120,
      h = 26,
      max = Math.max(...data),
      min = Math.min(...data);
    const sx = w / (data.length - 1);
    const y = v => h - (v - min) / (max - min || 1) * (h - 4) - 2;
    const line = data.map((d, i) => (i ? "L" : "M") + (i * sx).toFixed(1) + "," + y(d).toFixed(1)).join(" ");
    const col = up === false ? "var(--status-danger-solid)" : "var(--brand-primary)";
    return /*#__PURE__*/React.createElement("svg", {
      viewBox: "0 0 " + w + " " + h,
      width: "100%",
      height: h,
      preserveAspectRatio: "none",
      style: {
        display: "block"
      }
    }, /*#__PURE__*/React.createElement("path", {
      d: line,
      fill: "none",
      stroke: col,
      strokeWidth: "1.8",
      strokeLinejoin: "round",
      strokeLinecap: "round"
    }));
  }
  function EverflowStat({
    m
  }) {
    const pctColor = m.up === null ? "var(--text-faint)" : m.up ? "var(--status-positive-fg)" : "var(--status-danger-fg)";
    return /*#__PURE__*/React.createElement("div", {
      style: {
        background: "var(--surface-card)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-md)",
        boxShadow: "var(--shadow-sm)",
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 9,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 600,
        color: "var(--text-strong)",
        whiteSpace: "nowrap",
        overflow: "hidden",
        textOverflow: "ellipsis"
      }
    }, m.label), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        color: "var(--text-muted)"
      }
    }, "Current Month"), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        fontWeight: 600,
        color: pctColor
      }
    }, m.pct)), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 22,
        fontWeight: 700,
        color: "var(--text-strong)",
        fontVariantNumeric: "tabular-nums",
        lineHeight: 1
      }
    }, m.value), /*#__PURE__*/React.createElement(Spark, {
      data: m.spark,
      up: m.up
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column"
      }
    }, [["Today", m.today], ["Yesterday", m.yest], ["Last Month", m.last]].map(([k, v], i) => /*#__PURE__*/React.createElement("div", {
      key: k,
      style: {
        display: "flex",
        justifyContent: "space-between",
        padding: "7px 0",
        borderTop: i ? "1px solid var(--divider)" : "none",
        fontSize: 12
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--text-muted)"
      }
    }, k), /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--text-body)",
        fontWeight: 500,
        fontFamily: m.money ? "var(--font-mono)" : "inherit",
        fontVariantNumeric: "tabular-nums"
      }
    }, v)))));
  }
  function Dashboard() {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        gap: 20
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "grid",
        gridAutoFlow: "column",
        gridAutoColumns: "minmax(212px, 1fr)",
        gap: 14,
        overflowX: "auto",
        paddingBottom: 4
      }
    }, welcomeCards.map(c => {
      const accent = c.primary ? "var(--brand-primary)" : "#fbbf24";
      return /*#__PURE__*/React.createElement("div", {
        key: c.title,
        style: {
          background: "#0e1726",
          border: "1px solid " + (c.primary ? "var(--brand-primary)" : "rgba(255,255,255,.1)"),
          borderRadius: "var(--radius-md)",
          padding: 18,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          minHeight: 196,
          boxShadow: c.primary ? "0 0 0 3px color-mix(in srgb, var(--brand-primary) 18%, transparent)" : "none"
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          color: accent
        }
      }, /*#__PURE__*/React.createElement(Icon, {
        name: c.icon,
        size: 24
      })), /*#__PURE__*/React.createElement("div", {
        style: {
          fontSize: 15,
          fontWeight: 700,
          color: accent,
          lineHeight: 1.25
        }
      }, c.title), /*#__PURE__*/React.createElement("p", {
        style: {
          fontSize: 12.5,
          color: "#9fb0d0",
          lineHeight: 1.5,
          flex: 1,
          margin: 0
        }
      }, c.body), c.cta && /*#__PURE__*/React.createElement("button", {
        style: {
          alignSelf: "stretch",
          marginTop: "auto",
          padding: "9px 14px",
          borderRadius: "var(--radius-sm)",
          border: "none",
          background: "var(--brand-primary)",
          color: "var(--brand-primary-fg)",
          fontSize: 12.5,
          fontWeight: 600,
          cursor: "pointer",
          fontFamily: "var(--font-sans)"
        }
      }, c.cta));
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(168px, 1fr))",
        gap: 14,
        alignItems: "stretch"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        background: "var(--surface-card)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-md)",
        boxShadow: "var(--shadow-sm)",
        padding: 16,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 12,
        textAlign: "center",
        cursor: "pointer"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 46,
        height: 46,
        borderRadius: "var(--radius-md)",
        background: "var(--brand-tint)",
        color: "var(--brand-primary)",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "link",
      size: 22
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 600,
        color: "var(--text-strong)"
      }
    }, "Tracking & Asset Generator")), everflowMetrics.map(m => /*#__PURE__*/React.createElement(EverflowStat, {
      key: m.label,
      m: m
    }))), /*#__PURE__*/React.createElement(Card, {
      padding: "lg"
    }, /*#__PURE__*/React.createElement(CardHeader, {
      title: "Performance",
      subtitle: "Current month vs last month",
      actions: /*#__PURE__*/React.createElement(Select, {
        size: "sm",
        options: ["Revenue, Approved Conversions", "Clicks, Conversions"]
      })
    }), /*#__PURE__*/React.createElement(MiniChart, {
      data: chartData
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 18,
        marginTop: 12,
        fontSize: 12,
        color: "var(--text-muted)"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 6
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 18,
        height: 3,
        background: "var(--brand-primary)",
        borderRadius: 2
      }
    }), " Revenue"), /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 6
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 18,
        height: 0,
        borderTop: "2px dashed var(--text-faint)"
      }
    }), " Approved conversions"))), /*#__PURE__*/React.createElement(Card, {
      padding: "none"
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: "16px 20px",
        borderBottom: "1px solid var(--divider)"
      }
    }, /*#__PURE__*/React.createElement("h3", {
      style: {
        fontSize: "var(--text-lg)",
        fontWeight: 600
      }
    }, "Recent conversions")), /*#__PURE__*/React.createElement(DataTable, {
      dense: true,
      rowKey: "id",
      style: {
        border: "none",
        borderRadius: 0
      },
      columns: [{
        key: "time",
        header: "Time",
        muted: true,
        mono: true,
        width: 70
      }, {
        key: "offer",
        header: "Offer",
        sortable: true
      }, {
        key: "geo",
        header: "Geo",
        muted: true
      }, {
        key: "status",
        header: "Status",
        render: v => /*#__PURE__*/React.createElement(StatusPill, {
          status: v,
          size: "sm"
        })
      }, {
        key: "payout",
        header: "Payout",
        align: "right",
        mono: true,
        sortable: true,
        render: v => money(v)
      }],
      rows: recentConv
    })));
  }

  /* ---------- OFFERS ---------- */
  const offers = [{
    title: "Crypto Wallet Signup",
    cat: "Crypto",
    model: "CPA",
    geo: "KE · NG · ZA",
    payout: 14.5,
    rev: "CPA"
  }, {
    title: "Neobank Account CPL",
    cat: "Finance",
    model: "CPL",
    geo: "NG",
    payout: 9.0,
    rev: "CPL"
  }, {
    title: "Forex Broker Deposit",
    cat: "Finance",
    model: "CPA",
    geo: "ZA · KE",
    payout: 120.0,
    rev: "CPA"
  }, {
    title: "Sports Betting FTD",
    cat: "iGaming",
    model: "CPA",
    geo: "KE · TZ",
    payout: 38.0,
    rev: "CPA"
  }, {
    title: "VPN Annual Plan",
    cat: "Software",
    model: "RevShare",
    geo: "Global",
    payout: 22.0,
    rev: "RevShare"
  }, {
    title: "E-learning Trial",
    cat: "Education",
    model: "CPL",
    geo: "KE · UG",
    payout: 4.5,
    rev: "CPL"
  }];
  const catTone = {
    Crypto: "brand",
    Finance: "info",
    iGaming: "warning",
    Software: "positive",
    Education: "neutral"
  };
  function Offers() {
    const [q, setQ] = React.useState("");
    const list = offers.filter(o => o.title.toLowerCase().includes(q.toLowerCase()));
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        gap: 18
      }
    }, /*#__PURE__*/React.createElement(FilterBar, {
      onReset: () => setQ(""),
      actions: /*#__PURE__*/React.createElement(Button, null, "Apply filters")
    }, /*#__PURE__*/React.createElement(Input, {
      label: "Search",
      icon: "search",
      placeholder: "Search by name",
      value: q,
      onChange: e => setQ(e.target.value),
      wrapStyle: {
        flex: 1,
        minWidth: 180
      }
    }), /*#__PURE__*/React.createElement(Select, {
      label: "Category",
      options: ["All categories", "Crypto", "Finance", "iGaming", "Software"]
    }), /*#__PURE__*/React.createElement(Select, {
      label: "Revenue model",
      options: ["Any model", "CPA", "CPL", "RevShare"]
    }), /*#__PURE__*/React.createElement(Select, {
      label: "Country",
      options: ["Any country", "Kenya", "Nigeria", "South Africa"]
    })), list.length === 0 ? /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement(EmptyState, {
      icon: "tag",
      title: "No offers match your search",
      description: "Try a different keyword or reset the filters.",
      action: /*#__PURE__*/React.createElement(Button, {
        variant: "secondary",
        onClick: () => setQ("")
      }, "Reset")
    })) : /*#__PURE__*/React.createElement("div", {
      style: {
        display: "grid",
        gridTemplateColumns: "repeat(3, 1fr)",
        gap: 16
      }
    }, list.map(o => /*#__PURE__*/React.createElement(Card, {
      key: o.title,
      interactive: true,
      padding: "none",
      style: {
        overflow: "hidden",
        display: "flex",
        flexDirection: "column"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        height: 92,
        background: "linear-gradient(135deg, color-mix(in srgb, var(--brand-primary) 85%, #000), var(--brand-secondary))",
        display: "flex",
        alignItems: "center",
        justifyContent: "center"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: o.cat === "Crypto" ? "dollar-sign" : o.cat === "Finance" ? "credit-card" : o.cat === "iGaming" ? "target" : "tag",
      size: 30,
      style: {
        color: "rgba(255,255,255,.9)"
      }
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        flex: 1
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 6,
        flexWrap: "wrap"
      }
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: catTone[o.cat]
    }, o.cat), /*#__PURE__*/React.createElement(Badge, {
      tone: "neutral",
      outline: true
    }, o.rev)), /*#__PURE__*/React.createElement("h3", {
      style: {
        fontSize: "var(--text-md)",
        fontWeight: 600
      }
    }, o.title), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: "var(--text-muted)",
        display: "flex",
        alignItems: "center",
        gap: 5
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "globe",
      size: 13
    }), " ", o.geo), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: "auto",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        paddingTop: 8,
        borderTop: "1px solid var(--divider)"
      }
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 10,
        textTransform: "uppercase",
        letterSpacing: ".06em",
        color: "var(--text-faint)"
      }
    }, "Payout"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: 17,
        fontWeight: 600,
        color: "var(--text-strong)"
      }
    }, money(o.payout))), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "secondary",
      iconRight: "chevron-right"
    }, "Details")))))));
  }

  /* ---------- PAYOUTS ---------- */
  const payoutHistory = [{
    id: 4821,
    amount: 2480.0,
    method: "Crypto · USDT",
    status: "Paid",
    period: "May 2026",
    ref: "0x9f…a21"
  }, {
    id: 4720,
    amount: 1960.0,
    method: "PayPal",
    status: "Paid",
    period: "Apr 2026",
    ref: "PP-88231"
  }, {
    id: 4655,
    amount: 2110.0,
    method: "Crypto · USDT",
    status: "Processing",
    period: "Jun 2026",
    ref: "—"
  }];
  function Payouts({
    onRequest
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        gap: 18
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "grid",
        gridTemplateColumns: "repeat(3, 1fr)",
        gap: 16
      }
    }, /*#__PURE__*/React.createElement(StatTile, {
      label: "Pending earnings",
      value: "$2,110.00",
      icon: "clock",
      accent: true,
      hint: "Min threshold $100 \xB7 Net 30"
    }), /*#__PURE__*/React.createElement(StatTile, {
      label: "Lifetime paid",
      value: "$24,310.00",
      icon: "check-circle"
    }), /*#__PURE__*/React.createElement(StatTile, {
      label: "Next payout",
      value: "Jul 1",
      icon: "wallet",
      hint: "Auto-scheduled"
    })), /*#__PURE__*/React.createElement(Card, {
      padding: "none"
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "16px 20px",
        borderBottom: "1px solid var(--divider)"
      }
    }, /*#__PURE__*/React.createElement("h3", {
      style: {
        fontSize: "var(--text-lg)",
        fontWeight: 600
      }
    }, "Payout methods"), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      iconLeft: "plus",
      onClick: onRequest
    }, "Add method")), /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 20,
        display: "flex",
        flexDirection: "column",
        gap: 10
      }
    }, [{
      m: "Crypto · USDT (TRC-20)",
      d: "TQn9…f3Kd8a",
      def: true,
      ver: true
    }, {
      m: "PayPal",
      d: "grace@trafficlab.io",
      def: false,
      ver: true
    }].map(x => /*#__PURE__*/React.createElement("div", {
      key: x.m,
      style: {
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "12px 14px",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-sm)"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: x.m.startsWith("Crypto") ? "wallet" : "credit-card",
      size: 18,
      style: {
        color: "var(--text-muted)"
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 14,
        fontWeight: 500,
        color: "var(--text-strong)"
      }
    }, x.m), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: "var(--text-muted)",
        fontFamily: "var(--font-mono)"
      }
    }, x.d)), x.def && /*#__PURE__*/React.createElement(Badge, {
      tone: "brand"
    }, "Default"), /*#__PURE__*/React.createElement(StatusPill, {
      status: "Verified",
      size: "sm"
    }))))), /*#__PURE__*/React.createElement(Card, {
      padding: "none"
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: "16px 20px",
        borderBottom: "1px solid var(--divider)"
      }
    }, /*#__PURE__*/React.createElement("h3", {
      style: {
        fontSize: "var(--text-lg)",
        fontWeight: 600
      }
    }, "Payout history")), /*#__PURE__*/React.createElement(DataTable, {
      rowKey: "id",
      style: {
        border: "none",
        borderRadius: 0
      },
      columns: [{
        key: "id",
        header: "#",
        muted: true,
        mono: true,
        width: 70
      }, {
        key: "period",
        header: "Period"
      }, {
        key: "method",
        header: "Method"
      }, {
        key: "status",
        header: "Status",
        render: v => /*#__PURE__*/React.createElement(StatusPill, {
          status: v,
          size: "sm"
        })
      }, {
        key: "ref",
        header: "Reference",
        mono: true,
        muted: true
      }, {
        key: "amount",
        header: "Amount",
        align: "right",
        mono: true,
        render: v => money(v)
      }],
      rows: payoutHistory
    })));
  }
  window.AffiliateScreens = {
    Login,
    Dashboard,
    Offers,
    Payouts
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/affiliate/screens.jsx", error: String((e && e.message) || e) }); }

// ui_kits/affiliate/tweaks-panel.jsx
try { (() => {
// @ds-adherence-ignore -- omelette starter scaffold (raw elements/hex/px by design)

/* BEGIN USAGE */
// tweaks-panel.jsx
// Reusable Tweaks shell + form-control helpers.
// Exports (to window): useTweaks, TweaksPanel, TweakSection, TweakRow, TweakSlider,
//   TweakToggle, TweakRadio, TweakSelect, TweakText, TweakNumber, TweakColor, TweakButton.
//
// Owns the host protocol (listens for __activate_edit_mode / __deactivate_edit_mode,
// posts __edit_mode_available / __edit_mode_set_keys / __edit_mode_dismissed) so
// individual prototypes don't re-roll it. Ships a consistent set of controls so you
// don't hand-draw <input type="range">, segmented radios, steppers, etc.
//
// Usage (in an HTML file that loads React + Babel):
//
//   const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
//     "primaryColor": "#D97757",
//     "palette": ["#D97757", "#29261b", "#f6f4ef"],
//     "fontSize": 16,
//     "density": "regular",
//     "dark": false
//   }/*EDITMODE-END*/;
//
//   function App() {
//     const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
//     return (
//       <div style={{ fontSize: t.fontSize, color: t.primaryColor }}>
//         Hello
//         <TweaksPanel>
//           <TweakSection label="Typography" />
//           <TweakSlider label="Font size" value={t.fontSize} min={10} max={32} unit="px"
//                        onChange={(v) => setTweak('fontSize', v)} />
//           <TweakRadio  label="Density" value={t.density}
//                        options={['compact', 'regular', 'comfy']}
//                        onChange={(v) => setTweak('density', v)} />
//           <TweakSection label="Theme" />
//           <TweakColor  label="Primary" value={t.primaryColor}
//                        options={['#D97757', '#2A6FDB', '#1F8A5B', '#7A5AE0']}
//                        onChange={(v) => setTweak('primaryColor', v)} />
//           <TweakColor  label="Palette" value={t.palette}
//                        options={[['#D97757', '#29261b', '#f6f4ef'],
//                                  ['#475569', '#0f172a', '#f1f5f9']]}
//                        onChange={(v) => setTweak('palette', v)} />
//           <TweakToggle label="Dark mode" value={t.dark}
//                        onChange={(v) => setTweak('dark', v)} />
//         </TweaksPanel>
//       </div>
//     );
//   }
//
// TweakRadio is the segmented control for 2–3 short options (auto-falls-back to
// TweakSelect past ~16/~10 chars per label); reach for TweakSelect directly when
// options are many or long. For color tweaks always curate 3-4 options rather than
// a free picker; an option can also be a whole 2–5 color palette (the stored value
// is the array). The Tweak* controls are a floor, not a ceiling — build custom
// controls inside the panel if a tweak calls for UI they don't cover.
/* END USAGE */
// ─────────────────────────────────────────────────────────────────────────────

const __TWEAKS_STYLE = `
  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:280px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    transform:scale(var(--dc-inv-zoom,1));transform-origin:bottom right;
    background:rgba(250,249,247,.78);color:#29261b;
    -webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%);
    border:.5px solid rgba(255,255,255,.6);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 40px rgba(0,0,0,.18);
    font:11.5px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:10px 8px 10px 14px;cursor:move;user-select:none}
  .twk-hd b{font-size:12px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:rgba(41,38,27,.55);
    width:22px;height:22px;border-radius:6px;cursor:default;font-size:13px;line-height:1}
  .twk-x:hover{background:rgba(0,0,0,.06);color:#29261b}
  .twk-body{padding:2px 14px 14px;display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;overflow-x:hidden;min-height:0;
    scrollbar-width:thin;scrollbar-color:rgba(0,0,0,.15) transparent}
  .twk-body::-webkit-scrollbar{width:8px}
  .twk-body::-webkit-scrollbar-track{background:transparent;margin:2px}
  .twk-body::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:4px;
    border:2px solid transparent;background-clip:content-box}
  .twk-body::-webkit-scrollbar-thumb:hover{background:rgba(0,0,0,.25);
    border:2px solid transparent;background-clip:content-box}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;
    color:rgba(41,38,27,.72)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-val{color:rgba(41,38,27,.5);font-variant-numeric:tabular-nums}

  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:rgba(41,38,27,.45);padding:10px 0 0}
  .twk-sect:first-child{padding-top:0}

  .twk-field{appearance:none;box-sizing:border-box;width:100%;min-width:0;height:26px;padding:0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;
    background:rgba(255,255,255,.6);color:inherit;font:inherit;outline:none}
  .twk-field:focus{border-color:rgba(0,0,0,.25);background:rgba(255,255,255,.85)}
  select.twk-field{padding-right:22px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path fill='rgba(0,0,0,.5)' d='M0 0h10L5 6z'/></svg>");
    background-repeat:no-repeat;background-position:right 8px center}

  .twk-slider{appearance:none;-webkit-appearance:none;width:100%;height:4px;margin:6px 0;
    border-radius:999px;background:rgba(0,0,0,.12);outline:none}
  .twk-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:14px;height:14px;border-radius:50%;background:#fff;
    border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}
  .twk-slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
    background:#fff;border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}

  .twk-seg{position:relative;display:flex;padding:2px;border-radius:8px;
    background:rgba(0,0,0,.06);user-select:none}
  .twk-seg-thumb{position:absolute;top:2px;bottom:2px;border-radius:6px;
    background:rgba(255,255,255,.9);box-shadow:0 1px 2px rgba(0,0,0,.12);
    transition:left .15s cubic-bezier(.3,.7,.4,1),width .15s}
  .twk-seg.dragging .twk-seg-thumb{transition:none}
  .twk-seg button{appearance:none;position:relative;z-index:1;flex:1;border:0;
    background:transparent;color:inherit;font:inherit;font-weight:500;min-height:22px;
    border-radius:6px;cursor:default;padding:4px 6px;line-height:1.2;
    overflow-wrap:anywhere}

  .twk-toggle{position:relative;width:32px;height:18px;border:0;border-radius:999px;
    background:rgba(0,0,0,.15);transition:background .15s;cursor:default;padding:0}
  .twk-toggle[data-on="1"]{background:#34c759}
  .twk-toggle i{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;
    background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
  .twk-toggle[data-on="1"] i{transform:translateX(14px)}

  .twk-num{display:flex;align-items:center;box-sizing:border-box;min-width:0;height:26px;padding:0 0 0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;background:rgba(255,255,255,.6)}
  .twk-num-lbl{font-weight:500;color:rgba(41,38,27,.6);cursor:ew-resize;
    user-select:none;padding-right:8px}
  .twk-num input{flex:1;min-width:0;height:100%;border:0;background:transparent;
    font:inherit;font-variant-numeric:tabular-nums;text-align:right;padding:0 8px 0 0;
    outline:none;color:inherit;-moz-appearance:textfield}
  .twk-num input::-webkit-inner-spin-button,.twk-num input::-webkit-outer-spin-button{
    -webkit-appearance:none;margin:0}
  .twk-num-unit{padding-right:8px;color:rgba(41,38,27,.45)}

  .twk-btn{appearance:none;height:26px;padding:0 12px;border:0;border-radius:7px;
    background:rgba(0,0,0,.78);color:#fff;font:inherit;font-weight:500;cursor:default}
  .twk-btn:hover{background:rgba(0,0,0,.88)}
  .twk-btn.secondary{background:rgba(0,0,0,.06);color:inherit}
  .twk-btn.secondary:hover{background:rgba(0,0,0,.1)}

  .twk-swatch{appearance:none;-webkit-appearance:none;width:56px;height:22px;
    border:.5px solid rgba(0,0,0,.1);border-radius:6px;padding:0;cursor:default;
    background:transparent;flex-shrink:0}
  .twk-swatch::-webkit-color-swatch-wrapper{padding:0}
  .twk-swatch::-webkit-color-swatch{border:0;border-radius:5.5px}
  .twk-swatch::-moz-color-swatch{border:0;border-radius:5.5px}

  .twk-chips{display:flex;gap:6px}
  .twk-chip{position:relative;appearance:none;flex:1;min-width:0;height:46px;
    padding:0;border:0;border-radius:6px;overflow:hidden;cursor:default;
    box-shadow:0 0 0 .5px rgba(0,0,0,.12),0 1px 2px rgba(0,0,0,.06);
    transition:transform .12s cubic-bezier(.3,.7,.4,1),box-shadow .12s}
  .twk-chip:hover{transform:translateY(-1px);
    box-shadow:0 0 0 .5px rgba(0,0,0,.18),0 4px 10px rgba(0,0,0,.12)}
  .twk-chip[data-on="1"]{box-shadow:0 0 0 1.5px rgba(0,0,0,.85),
    0 2px 6px rgba(0,0,0,.15)}
  .twk-chip>span{position:absolute;top:0;bottom:0;right:0;width:34%;
    display:flex;flex-direction:column;box-shadow:-1px 0 0 rgba(0,0,0,.1)}
  .twk-chip>span>i{flex:1;box-shadow:0 -1px 0 rgba(0,0,0,.1)}
  .twk-chip>span>i:first-child{box-shadow:none}
  .twk-chip svg{position:absolute;top:6px;left:6px;width:13px;height:13px;
    filter:drop-shadow(0 1px 1px rgba(0,0,0,.3))}
`;

// ── useTweaks ───────────────────────────────────────────────────────────────
// Single source of truth for tweak values. setTweak persists via the host
// (__edit_mode_set_keys → host rewrites the EDITMODE block on disk).
function useTweaks(defaults) {
  const [values, setValues] = React.useState(defaults);
  // Accepts either setTweak('key', value) or setTweak({ key: value, ... }) so a
  // useState-style call doesn't write a "[object Object]" key into the persisted
  // JSON block.
  const setTweak = React.useCallback((keyOrEdits, val) => {
    const edits = typeof keyOrEdits === 'object' && keyOrEdits !== null ? keyOrEdits : {
      [keyOrEdits]: val
    };
    setValues(prev => ({
      ...prev,
      ...edits
    }));
    window.parent.postMessage({
      type: '__edit_mode_set_keys',
      edits
    }, '*');
    // Same-window signal so in-page listeners (deck-stage rail thumbnails)
    // can react — the parent message only reaches the host, not peers.
    window.dispatchEvent(new CustomEvent('tweakchange', {
      detail: edits
    }));
  }, []);
  return [values, setTweak];
}

// ── TweaksPanel ─────────────────────────────────────────────────────────────
// Floating shell. Registers the protocol listener BEFORE announcing
// availability — if the announce ran first, the host's activate could land
// before our handler exists and the toolbar toggle would silently no-op.
// The close button posts __edit_mode_dismissed so the host's toolbar toggle
// flips off in lockstep; the host echoes __deactivate_edit_mode back which
// is what actually hides the panel.
function TweaksPanel({
  title = 'Tweaks',
  children
}) {
  const [open, setOpen] = React.useState(false);
  const dragRef = React.useRef(null);
  const offsetRef = React.useRef({
    x: 16,
    y: 16
  });
  const PAD = 16;
  const clampToViewport = React.useCallback(() => {
    const panel = dragRef.current;
    if (!panel) return;
    const w = panel.offsetWidth,
      h = panel.offsetHeight;
    const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
    const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
    offsetRef.current = {
      x: Math.min(maxRight, Math.max(PAD, offsetRef.current.x)),
      y: Math.min(maxBottom, Math.max(PAD, offsetRef.current.y))
    };
    panel.style.right = offsetRef.current.x + 'px';
    panel.style.bottom = offsetRef.current.y + 'px';
  }, []);
  React.useEffect(() => {
    if (!open) return;
    clampToViewport();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', clampToViewport);
      return () => window.removeEventListener('resize', clampToViewport);
    }
    const ro = new ResizeObserver(clampToViewport);
    ro.observe(document.documentElement);
    return () => ro.disconnect();
  }, [open, clampToViewport]);
  React.useEffect(() => {
    const onMsg = e => {
      const t = e?.data?.type;
      if (t === '__activate_edit_mode') setOpen(true);else if (t === '__deactivate_edit_mode') setOpen(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({
      type: '__edit_mode_available'
    }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);
  const dismiss = () => {
    setOpen(false);
    window.parent.postMessage({
      type: '__edit_mode_dismissed'
    }, '*');
  };
  const onDragStart = e => {
    const panel = dragRef.current;
    if (!panel) return;
    const r = panel.getBoundingClientRect();
    const sx = e.clientX,
      sy = e.clientY;
    const startRight = window.innerWidth - r.right;
    const startBottom = window.innerHeight - r.bottom;
    const move = ev => {
      offsetRef.current = {
        x: startRight - (ev.clientX - sx),
        y: startBottom - (ev.clientY - sy)
      };
      clampToViewport();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };
  if (!open) return null;
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("style", null, __TWEAKS_STYLE), /*#__PURE__*/React.createElement("div", {
    ref: dragRef,
    className: "twk-panel",
    "data-omelette-chrome": "",
    style: {
      right: offsetRef.current.x,
      bottom: offsetRef.current.y
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-hd",
    onMouseDown: onDragStart
  }, /*#__PURE__*/React.createElement("b", null, title), /*#__PURE__*/React.createElement("button", {
    className: "twk-x",
    "aria-label": "Close tweaks",
    onMouseDown: e => e.stopPropagation(),
    onClick: dismiss
  }, "\u2715")), /*#__PURE__*/React.createElement("div", {
    className: "twk-body"
  }, children)));
}

// ── Layout helpers ──────────────────────────────────────────────────────────

function TweakSection({
  label,
  children
}) {
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "twk-sect"
  }, label), children);
}
function TweakRow({
  label,
  value,
  children,
  inline = false
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: inline ? 'twk-row twk-row-h' : 'twk-row'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label), value != null && /*#__PURE__*/React.createElement("span", {
    className: "twk-val"
  }, value)), children);
}

// ── Controls ────────────────────────────────────────────────────────────────

function TweakSlider({
  label,
  value,
  min = 0,
  max = 100,
  step = 1,
  unit = '',
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label,
    value: `${value}${unit}`
  }, /*#__PURE__*/React.createElement("input", {
    type: "range",
    className: "twk-slider",
    min: min,
    max: max,
    step: step,
    value: value,
    onChange: e => onChange(Number(e.target.value))
  }));
}
function TweakToggle({
  label,
  value,
  onChange
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-row twk-row-h"
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "twk-toggle",
    "data-on": value ? '1' : '0',
    role: "switch",
    "aria-checked": !!value,
    onClick: () => onChange(!value)
  }, /*#__PURE__*/React.createElement("i", null)));
}
function TweakRadio({
  label,
  value,
  options,
  onChange
}) {
  const trackRef = React.useRef(null);
  const [dragging, setDragging] = React.useState(false);
  // The active value is read by pointer-move handlers attached for the lifetime
  // of a drag — ref it so a stale closure doesn't fire onChange for every move.
  const valueRef = React.useRef(value);
  valueRef.current = value;

  // Segments wrap mid-word once per-segment width runs out. The track is
  // ~248px (280 panel − 28 body pad − 4 seg pad), each button loses 12px
  // to its own padding, and 11.5px system-ui averages ~6.3px/char — so 2
  // options fit ~16 chars each, 3 fit ~10. Past that (or >3 options), fall
  // back to a dropdown rather than wrap.
  const labelLen = o => String(typeof o === 'object' ? o.label : o).length;
  const maxLen = options.reduce((m, o) => Math.max(m, labelLen(o)), 0);
  const fitsAsSegments = maxLen <= ({
    2: 16,
    3: 10
  }[options.length] ?? 0);
  if (!fitsAsSegments) {
    // <select> emits strings — map back to the original option value so the
    // fallback stays type-preserving (numbers, booleans) like the segment path.
    const resolve = s => {
      const m = options.find(o => String(typeof o === 'object' ? o.value : o) === s);
      return m === undefined ? s : typeof m === 'object' ? m.value : m;
    };
    return /*#__PURE__*/React.createElement(TweakSelect, {
      label: label,
      value: value,
      options: options,
      onChange: s => onChange(resolve(s))
    });
  }
  const opts = options.map(o => typeof o === 'object' ? o : {
    value: o,
    label: o
  });
  const idx = Math.max(0, opts.findIndex(o => o.value === value));
  const n = opts.length;
  const segAt = clientX => {
    const r = trackRef.current.getBoundingClientRect();
    const inner = r.width - 4;
    const i = Math.floor((clientX - r.left - 2) / inner * n);
    return opts[Math.max(0, Math.min(n - 1, i))].value;
  };
  const onPointerDown = e => {
    setDragging(true);
    const v0 = segAt(e.clientX);
    if (v0 !== valueRef.current) onChange(v0);
    const move = ev => {
      if (!trackRef.current) return;
      const v = segAt(ev.clientX);
      if (v !== valueRef.current) onChange(v);
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    ref: trackRef,
    role: "radiogroup",
    onPointerDown: onPointerDown,
    className: dragging ? 'twk-seg dragging' : 'twk-seg'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-seg-thumb",
    style: {
      left: `calc(2px + ${idx} * (100% - 4px) / ${n})`,
      width: `calc((100% - 4px) / ${n})`
    }
  }), opts.map(o => /*#__PURE__*/React.createElement("button", {
    key: o.value,
    type: "button",
    role: "radio",
    "aria-checked": o.value === value
  }, o.label))));
}
function TweakSelect({
  label,
  value,
  options,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("select", {
    className: "twk-field",
    value: value,
    onChange: e => onChange(e.target.value)
  }, options.map(o => {
    const v = typeof o === 'object' ? o.value : o;
    const l = typeof o === 'object' ? o.label : o;
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v
    }, l);
  })));
}
function TweakText({
  label,
  value,
  placeholder,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("input", {
    className: "twk-field",
    type: "text",
    value: value,
    placeholder: placeholder,
    onChange: e => onChange(e.target.value)
  }));
}
function TweakNumber({
  label,
  value,
  min,
  max,
  step = 1,
  unit = '',
  onChange
}) {
  const clamp = n => {
    if (min != null && n < min) return min;
    if (max != null && n > max) return max;
    return n;
  };
  const startRef = React.useRef({
    x: 0,
    val: 0
  });
  const onScrubStart = e => {
    e.preventDefault();
    startRef.current = {
      x: e.clientX,
      val: value
    };
    const decimals = (String(step).split('.')[1] || '').length;
    const move = ev => {
      const dx = ev.clientX - startRef.current.x;
      const raw = startRef.current.val + dx * step;
      const snapped = Math.round(raw / step) * step;
      onChange(clamp(Number(snapped.toFixed(decimals))));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-num"
  }, /*#__PURE__*/React.createElement("span", {
    className: "twk-num-lbl",
    onPointerDown: onScrubStart
  }, label), /*#__PURE__*/React.createElement("input", {
    type: "number",
    value: value,
    min: min,
    max: max,
    step: step,
    onChange: e => onChange(clamp(Number(e.target.value)))
  }), unit && /*#__PURE__*/React.createElement("span", {
    className: "twk-num-unit"
  }, unit));
}

// Relative-luminance contrast pick — checkmarks drawn over a swatch need to
// read on both #111 and #fafafa without per-option configuration. Hex input
// only (#rgb / #rrggbb); named or rgb()/hsl() colors fall through to "light".
function __twkIsLight(hex) {
  const h = String(hex).replace('#', '');
  const x = h.length === 3 ? h.replace(/./g, c => c + c) : h.padEnd(6, '0');
  const n = parseInt(x.slice(0, 6), 16);
  if (Number.isNaN(n)) return true;
  const r = n >> 16 & 255,
    g = n >> 8 & 255,
    b = n & 255;
  return r * 299 + g * 587 + b * 114 > 148000;
}
const __TwkCheck = ({
  light
}) => /*#__PURE__*/React.createElement("svg", {
  viewBox: "0 0 14 14",
  "aria-hidden": "true"
}, /*#__PURE__*/React.createElement("path", {
  d: "M3 7.2 5.8 10 11 4.2",
  fill: "none",
  strokeWidth: "2.2",
  strokeLinecap: "round",
  strokeLinejoin: "round",
  stroke: light ? 'rgba(0,0,0,.78)' : '#fff'
}));

// TweakColor — curated color/palette picker. Each option is either a single
// hex string or an array of 1-5 hex strings; the card adapts — a lone color
// renders solid, a palette renders colors[0] as the hero (left ~2/3) with the
// rest stacked in a sharp column on the right. onChange emits the
// option in the shape it was passed (string stays string, array stays array).
// Without options it falls back to the native color input for back-compat.
function TweakColor({
  label,
  value,
  options,
  onChange
}) {
  if (!options || !options.length) {
    return /*#__PURE__*/React.createElement("div", {
      className: "twk-row twk-row-h"
    }, /*#__PURE__*/React.createElement("div", {
      className: "twk-lbl"
    }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("input", {
      type: "color",
      className: "twk-swatch",
      value: value,
      onChange: e => onChange(e.target.value)
    }));
  }
  // Native <input type=color> emits lowercase hex per the HTML spec, so
  // compare case-insensitively. String() guards JSON.stringify(undefined),
  // which returns the primitive undefined (no .toLowerCase).
  const key = o => String(JSON.stringify(o)).toLowerCase();
  const cur = key(value);
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-chips",
    role: "radiogroup"
  }, options.map((o, i) => {
    const colors = Array.isArray(o) ? o : [o];
    const [hero, ...rest] = colors;
    const sup = rest.slice(0, 4);
    const on = key(o) === cur;
    return /*#__PURE__*/React.createElement("button", {
      key: i,
      type: "button",
      className: "twk-chip",
      role: "radio",
      "aria-checked": on,
      "data-on": on ? '1' : '0',
      "aria-label": colors.join(', '),
      title: colors.join(' · '),
      style: {
        background: hero
      },
      onClick: () => onChange(o)
    }, sup.length > 0 && /*#__PURE__*/React.createElement("span", null, sup.map((c, j) => /*#__PURE__*/React.createElement("i", {
      key: j,
      style: {
        background: c
      }
    }))), on && /*#__PURE__*/React.createElement(__TwkCheck, {
      light: __twkIsLight(hero)
    }));
  })));
}
function TweakButton({
  label,
  onClick,
  secondary = false
}) {
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: secondary ? 'twk-btn secondary' : 'twk-btn',
    onClick: onClick
  }, label);
}
Object.assign(window, {
  useTweaks,
  TweaksPanel,
  TweakSection,
  TweakRow,
  TweakSlider,
  TweakToggle,
  TweakRadio,
  TweakSelect,
  TweakText,
  TweakNumber,
  TweakColor,
  TweakButton
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/affiliate/tweaks-panel.jsx", error: String((e && e.message) || e) }); }

// ui_kits/marketing/screens.jsx
try { (() => {
/* Nexora — Public marketing surfaces: landing + adaptive /get-started/ lead form.
   Composes the design-system bundle. Exposes window.MarketingScreens. */
(function () {
  const NX = window.NexoraDesignSystem_985ae7;
  const {
    Button,
    Badge,
    Input,
    Select,
    Icon,
    StatusPill
  } = NX;
  function Logo({
    brandName,
    light
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 9
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 28,
        height: 28,
        borderRadius: 7,
        background: "var(--brand-primary)",
        color: "var(--brand-primary-fg)",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontWeight: 700,
        fontSize: 15
      }
    }, brandName[0]), /*#__PURE__*/React.createElement("span", {
      style: {
        fontWeight: 600,
        fontSize: 18,
        letterSpacing: "-0.01em",
        color: light ? "#fff" : "var(--text-strong)"
      }
    }, brandName));
  }

  /* ---------- LANDING ---------- */
  function Landing({
    brandName,
    onGetStarted
  }) {
    const props = [{
      icon: "mouse-pointer-click",
      title: "Real-time tracking",
      body: "Sub-second click and conversion tracking with S2S postbacks and HMAC-signed webhooks."
    }, {
      icon: "wallet",
      title: "Crypto + fiat payouts",
      body: "Pay affiliates in USDT, PayPal, Wise, Paxum or bank — with velocity controls and holds."
    }, {
      icon: "shield-check",
      title: "Fraud & controls",
      body: "Anomaly holds, velocity caps and an auditable approval layer before any funds move."
    }, {
      icon: "bar-chart",
      title: "Deep reporting",
      body: "Daily, offer and goal-level reporting that scales from thousands to millions of clicks."
    }];
    return /*#__PURE__*/React.createElement("div", {
      style: {
        background: "var(--surface-app)"
      }
    }, /*#__PURE__*/React.createElement("header", {
      style: {
        position: "sticky",
        top: 0,
        zIndex: 10,
        background: "rgba(13,19,32,.85)",
        backdropFilter: "blur(10px)",
        borderBottom: "1px solid rgba(255,255,255,.08)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        maxWidth: "var(--marketing-max)",
        margin: "0 auto",
        padding: "14px 24px",
        display: "flex",
        alignItems: "center",
        gap: 24
      }
    }, /*#__PURE__*/React.createElement(Logo, {
      brandName: brandName,
      light: true
    }), /*#__PURE__*/React.createElement("nav", {
      style: {
        display: "flex",
        gap: 22,
        marginLeft: 18
      }
    }, ["Product", "Pricing", "Docs", "Company"].map(l => /*#__PURE__*/React.createElement("a", {
      key: l,
      href: "#",
      style: {
        color: "#9fb0d0",
        fontSize: 14,
        textDecoration: "none"
      }
    }, l))), /*#__PURE__*/React.createElement("div", {
      style: {
        marginLeft: "auto",
        display: "flex",
        gap: 10,
        alignItems: "center"
      }
    }, /*#__PURE__*/React.createElement("a", {
      href: "#",
      style: {
        color: "#cbd5e1",
        fontSize: 14,
        textDecoration: "none"
      }
    }, "Sign in"), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      onClick: onGetStarted,
      iconRight: "arrow-right"
    }, "Get started")))), /*#__PURE__*/React.createElement("section", {
      style: {
        background: "#0d1320",
        color: "#fff",
        backgroundImage: "radial-gradient(ellipse 80% 60% at 50% -10%, color-mix(in srgb, var(--brand-primary) 32%, transparent), transparent)",
        borderBottom: "1px solid rgba(255,255,255,.06)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        maxWidth: "var(--marketing-max)",
        margin: "0 auto",
        padding: "76px 24px 84px",
        textAlign: "center"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        padding: "5px 12px",
        borderRadius: 999,
        border: "1px solid rgba(255,255,255,.16)",
        color: "#cbd5e1",
        fontSize: 13,
        marginBottom: 22
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 7,
        height: 7,
        borderRadius: "50%",
        background: "var(--brand-primary)"
      }
    }), " White-label affiliate platform"), /*#__PURE__*/React.createElement("h1", {
      style: {
        color: "#fff",
        fontSize: 60,
        fontWeight: 700,
        letterSpacing: "-0.03em",
        lineHeight: 1.04,
        maxWidth: "16ch",
        margin: "0 auto"
      }
    }, "Run your own affiliate network"), /*#__PURE__*/React.createElement("p", {
      style: {
        color: "#9fb0d0",
        fontSize: 19,
        lineHeight: 1.5,
        maxWidth: "54ch",
        margin: "20px auto 0"
      }
    }, "Nexora gives operators a fully-branded CPA platform \u2014 your colors, your logo, your domain. Track, optimize and pay out, all on infrastructure that moves real money safely."), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 12,
        justifyContent: "center",
        marginTop: 30
      }
    }, /*#__PURE__*/React.createElement(Button, {
      size: "lg",
      onClick: onGetStarted,
      iconRight: "arrow-right"
    }, "Request your network"), /*#__PURE__*/React.createElement(Button, {
      size: "lg",
      variant: "secondary",
      iconLeft: "file-text",
      style: {
        background: "rgba(255,255,255,.06)",
        color: "#fff",
        borderColor: "rgba(255,255,255,.2)"
      }
    }, "Read the docs")), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 28,
        justifyContent: "center",
        marginTop: 40,
        color: "#64748b",
        fontSize: 13,
        flexWrap: "wrap"
      }
    }, /*#__PURE__*/React.createElement("span", null, "Trusted by networks in 40+ countries"), /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        gap: 6,
        alignItems: "center"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "shield-check",
      size: 14
    }), " SOC-2 controls"), /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        gap: 6,
        alignItems: "center"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "globe",
      size: 14
    }), " Crypto + fiat")))), /*#__PURE__*/React.createElement("section", {
      style: {
        background: "var(--surface-card)",
        borderBottom: "1px solid var(--border-default)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        maxWidth: "var(--marketing-max)",
        margin: "0 auto",
        padding: "32px 24px",
        display: "grid",
        gridTemplateColumns: "repeat(4,1fr)",
        gap: 24
      }
    }, [["$48M+", "Paid to affiliates"], ["3.2B", "Clicks tracked / mo"], ["99.98%", "Tracking uptime"], ["40+", "Countries"]].map(([n, l]) => /*#__PURE__*/React.createElement("div", {
      key: l,
      style: {
        textAlign: "center"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: 30,
        fontWeight: 700,
        color: "var(--text-strong)"
      }
    }, n), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        color: "var(--text-muted)",
        marginTop: 4
      }
    }, l))))), /*#__PURE__*/React.createElement("section", {
      style: {
        maxWidth: "var(--marketing-max)",
        margin: "0 auto",
        padding: "72px 24px"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        textAlign: "center",
        marginBottom: 44
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "eyebrow",
      style: {
        color: "var(--brand-primary)"
      }
    }, "Everything in one platform"), /*#__PURE__*/React.createElement("h2", {
      style: {
        fontSize: 36,
        fontWeight: 600,
        letterSpacing: "-0.02em",
        marginTop: 8
      }
    }, "Built for performance marketing at scale")), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "grid",
        gridTemplateColumns: "repeat(2,1fr)",
        gap: 20
      }
    }, props.map(p => /*#__PURE__*/React.createElement("div", {
      key: p.title,
      style: {
        display: "flex",
        gap: 16,
        padding: 24,
        background: "var(--surface-card)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "var(--shadow-sm)"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 44,
        height: 44,
        flexShrink: 0,
        borderRadius: "var(--radius-md)",
        background: "var(--brand-tint)",
        color: "var(--brand-primary)",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: p.icon,
      size: 22
    })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h3", {
      style: {
        fontSize: "var(--text-lg)",
        fontWeight: 600
      }
    }, p.title), /*#__PURE__*/React.createElement("p", {
      style: {
        fontSize: 14,
        color: "var(--text-muted)",
        marginTop: 6,
        lineHeight: 1.55
      }
    }, p.body)))))), /*#__PURE__*/React.createElement("section", {
      style: {
        maxWidth: "var(--marketing-max)",
        margin: "0 auto 72px",
        padding: "0 24px"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        background: "linear-gradient(135deg, color-mix(in srgb, var(--brand-primary) 92%, #000), var(--brand-secondary))",
        borderRadius: "var(--radius-xl)",
        padding: "52px 40px",
        textAlign: "center",
        color: "#fff"
      }
    }, /*#__PURE__*/React.createElement("h2", {
      style: {
        color: "#fff",
        fontSize: 34,
        fontWeight: 700,
        letterSpacing: "-0.02em"
      }
    }, "Launch your network this quarter"), /*#__PURE__*/React.createElement("p", {
      style: {
        color: "rgba(255,255,255,.85)",
        fontSize: 17,
        marginTop: 12,
        maxWidth: "48ch",
        margin: "12px auto 0"
      }
    }, "Tell us what you're building and we'll set up a fully white-labeled platform with your brand."), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 26
      }
    }, /*#__PURE__*/React.createElement(Button, {
      size: "lg",
      onClick: onGetStarted,
      style: {
        background: "#fff",
        color: "var(--brand-secondary)",
        borderColor: "#fff"
      },
      iconRight: "arrow-right"
    }, "Get started")))), /*#__PURE__*/React.createElement("footer", {
      style: {
        borderTop: "1px solid var(--border-default)",
        background: "var(--surface-card)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        maxWidth: "var(--marketing-max)",
        margin: "0 auto",
        padding: "28px 24px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 12
      }
    }, /*#__PURE__*/React.createElement(Logo, {
      brandName: brandName
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13,
        color: "var(--text-muted)"
      }
    }, "\xA9 2026 ", brandName, " \xB7 Built by CloudTrade Centralised Systems"))));
  }

  /* ---------- GET STARTED (adaptive lead form) ---------- */
  const LEAD_TYPES = [{
    val: "SOLO",
    label: "Solo affiliate",
    desc: "I promote offers and want to earn payouts.",
    icon: "mouse-pointer-click"
  }, {
    val: "ADVERTISER",
    label: "Advertiser",
    desc: "I have offers and want quality traffic.",
    icon: "tag"
  }, {
    val: "NETWORK",
    label: "Network (white-label)",
    desc: "I want to run my own branded affiliate network.",
    icon: "building"
  }, {
    val: "OTHER",
    label: "Something else",
    desc: "Tell us what you have in mind.",
    icon: "help-circle"
  }];
  function GetStarted({
    brandName,
    onBack
  }) {
    const [type, setType] = React.useState(null);
    const [sent, setSent] = React.useState(false);
    const show = types => type && types.includes(type);
    return /*#__PURE__*/React.createElement("div", {
      style: {
        minHeight: "100%",
        background: "#0b1020",
        backgroundImage: "radial-gradient(ellipse at top, color-mix(in srgb, var(--brand-primary) 20%, transparent), transparent 60%)",
        color: "#e8edf7"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        maxWidth: "var(--form-max)",
        margin: "0 auto",
        padding: "40px 20px 80px"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 28
      }
    }, /*#__PURE__*/React.createElement(Logo, {
      brandName: brandName,
      light: true
    }), /*#__PURE__*/React.createElement("a", {
      href: "#",
      onClick: e => {
        e.preventDefault();
        onBack();
      },
      style: {
        color: "#9fb0d0",
        fontSize: 14,
        textDecoration: "none",
        display: "inline-flex",
        alignItems: "center",
        gap: 6
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "arrow-left-right",
      size: 14
    }), " Back to home")), sent ? /*#__PURE__*/React.createElement("div", {
      style: {
        background: "#121a30",
        border: "1px solid #26314f",
        borderRadius: "var(--radius-xl)",
        padding: "48px 28px",
        textAlign: "center"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 56,
        height: 56,
        borderRadius: "50%",
        background: "var(--status-positive-bg)",
        color: "var(--status-positive-fg)",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        margin: "0 auto 16px"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "check-circle",
      size: 28
    })), /*#__PURE__*/React.createElement("h1", {
      style: {
        color: "#fff",
        fontSize: 28,
        fontWeight: 600
      }
    }, "Thanks \u2014 we'll be in touch."), /*#__PURE__*/React.createElement("p", {
      style: {
        color: "#9fb0d0",
        fontSize: 16,
        marginTop: 10,
        maxWidth: "46ch",
        margin: "10px auto 0"
      }
    }, "Your request reached our team. We'll review the details and reach out shortly to talk about your network."), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 24
      }
    }, /*#__PURE__*/React.createElement(Button, {
      onClick: onBack,
      iconLeft: "arrow-left-right",
      style: {
        background: "var(--brand-primary)"
      }
    }, "Back to home"))) : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("h1", {
      style: {
        color: "#fff",
        fontSize: 34,
        fontWeight: 700,
        letterSpacing: "-0.02em"
      }
    }, "Request your network"), /*#__PURE__*/React.createElement("p", {
      style: {
        color: "#9fb0d0",
        fontSize: 16,
        marginTop: 8,
        maxWidth: "58ch"
      }
    }, "Tell us what you're building and we'll set you up with your own white-label platform. Only your name and email are required \u2014 everything else helps us tailor the conversation."), /*#__PURE__*/React.createElement("div", {
      style: {
        background: "#121a30",
        border: "1px solid #26314f",
        borderRadius: "var(--radius-xl)",
        padding: 28,
        marginTop: 24
      }
    }, /*#__PURE__*/React.createElement("fieldset", {
      style: {
        border: 0,
        padding: 0,
        margin: 0
      }
    }, /*#__PURE__*/React.createElement("legend", {
      style: {
        fontWeight: 600,
        fontSize: 17,
        color: "#fff",
        marginBottom: 14,
        padding: 0
      }
    }, "What are you looking for?"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "grid",
        gap: 10
      }
    }, LEAD_TYPES.map(t => {
      const sel = type === t.val;
      return /*#__PURE__*/React.createElement("label", {
        key: t.val,
        onClick: () => setType(t.val),
        style: {
          display: "flex",
          gap: 12,
          alignItems: "flex-start",
          border: `1px solid ${sel ? "var(--brand-primary)" : "#26314f"}`,
          background: sel ? "color-mix(in srgb, var(--brand-primary) 12%, transparent)" : "transparent",
          borderRadius: "var(--radius-md)",
          padding: "13px 15px",
          cursor: "pointer",
          transition: ".15s"
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          width: 34,
          height: 34,
          flexShrink: 0,
          borderRadius: "var(--radius-sm)",
          background: sel ? "var(--brand-primary)" : "#1a2440",
          color: sel ? "#fff" : "#9fb0d0",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center"
        }
      }, /*#__PURE__*/React.createElement(Icon, {
        name: t.icon,
        size: 18
      })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
        style: {
          fontWeight: 600,
          color: "#fff",
          fontSize: 15
        }
      }, t.label), /*#__PURE__*/React.createElement("div", {
        style: {
          color: "#9fb0d0",
          fontSize: 13,
          marginTop: 2
        }
      }, t.desc)), /*#__PURE__*/React.createElement("span", {
        style: {
          marginLeft: "auto",
          width: 18,
          height: 18,
          borderRadius: "50%",
          border: `2px solid ${sel ? "var(--brand-primary)" : "#3a466a"}`,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center"
        }
      }, sel && /*#__PURE__*/React.createElement("span", {
        style: {
          width: 9,
          height: 9,
          borderRadius: "50%",
          background: "var(--brand-primary)"
        }
      })));
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        height: 1,
        background: "#26314f",
        margin: "22px 0"
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 16
      }
    }, /*#__PURE__*/React.createElement(DarkField, {
      label: "Name",
      required: true
    }, /*#__PURE__*/React.createElement("input", {
      style: di,
      defaultValue: "",
      placeholder: "Jane Mwangi"
    })), /*#__PURE__*/React.createElement(DarkField, {
      label: "Email",
      required: true
    }, /*#__PURE__*/React.createElement("input", {
      style: di,
      type: "email",
      placeholder: "jane@company.com"
    })), /*#__PURE__*/React.createElement(DarkField, {
      label: "Phone"
    }, /*#__PURE__*/React.createElement("input", {
      style: di,
      placeholder: "+254\u2026"
    })), show(["ADVERTISER", "NETWORK", "OTHER"]) && /*#__PURE__*/React.createElement(DarkField, {
      label: "Company / brand"
    }, /*#__PURE__*/React.createElement("input", {
      style: di,
      placeholder: "Acme Media"
    })), /*#__PURE__*/React.createElement(DarkField, {
      label: "Country / region"
    }, /*#__PURE__*/React.createElement("select", {
      style: di
    }, /*#__PURE__*/React.createElement("option", null, "Kenya"), /*#__PURE__*/React.createElement("option", null, "Nigeria"), /*#__PURE__*/React.createElement("option", null, "South Africa"), /*#__PURE__*/React.createElement("option", null, "United Kingdom"))), show(["NETWORK", "ADVERTISER"]) && /*#__PURE__*/React.createElement(DarkField, {
      label: "Website / current platform"
    }, /*#__PURE__*/React.createElement("input", {
      style: di,
      placeholder: "https://"
    }))), show(["NETWORK"]) && /*#__PURE__*/React.createElement(DarkField, {
      label: "Expected scale",
      hint: "e.g. number of affiliates",
      style: {
        marginTop: 16
      }
    }, /*#__PURE__*/React.createElement("input", {
      style: di,
      placeholder: "500 affiliates"
    })), show(["SOLO", "ADVERTISER", "OTHER"]) && /*#__PURE__*/React.createElement(DarkField, {
      label: "Monthly volume",
      hint: "clicks or conversions per month",
      style: {
        marginTop: 16
      }
    }, /*#__PURE__*/React.createElement("input", {
      style: di,
      placeholder: "2M clicks"
    })), show(["ADVERTISER", "NETWORK", "OTHER"]) && /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 16
      }
    }, /*#__PURE__*/React.createElement(DarkLabel, null, "Verticals"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexWrap: "wrap",
        gap: 8
      }
    }, ["Crypto", "Finance", "iGaming", "Nutra", "Software", "E-commerce"].map(v => /*#__PURE__*/React.createElement(Chip, {
      key: v
    }, v)))), type && /*#__PURE__*/React.createElement(DarkField, {
      label: "What's prompting the move?",
      hint: "current pain / why looking",
      style: {
        marginTop: 16
      }
    }, /*#__PURE__*/React.createElement("textarea", {
      style: {
        ...di,
        minHeight: 84,
        resize: "vertical"
      },
      placeholder: "We're outgrowing our current tracker\u2026"
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 22
      }
    }, /*#__PURE__*/React.createElement(Button, {
      size: "lg",
      full: true,
      disabled: !type,
      onClick: () => setType && setSent(true),
      iconRight: "arrow-right"
    }, "Request your network"), !type && /*#__PURE__*/React.createElement("p", {
      style: {
        color: "#64748b",
        fontSize: 12,
        marginTop: 8,
        textAlign: "center"
      }
    }, "Select what you're looking for to continue"))))));
  }
  const di = {
    width: "100%",
    padding: "11px 13px",
    borderRadius: "var(--radius-sm)",
    border: "1px solid #26314f",
    background: "#0d1426",
    color: "#e8edf7",
    fontSize: 14,
    fontFamily: "var(--font-sans)",
    boxSizing: "border-box"
  };
  function DarkLabel({
    children
  }) {
    return /*#__PURE__*/React.createElement("label", {
      style: {
        display: "block",
        fontWeight: 600,
        fontSize: 13,
        color: "#cbd5e1",
        marginBottom: 6
      }
    }, children);
  }
  function DarkField({
    label,
    hint,
    required,
    children,
    style
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: style
    }, /*#__PURE__*/React.createElement(DarkLabel, null, label, " ", required && /*#__PURE__*/React.createElement("span", {
      style: {
        color: "#64748b",
        fontWeight: 400
      }
    }, "(required)"), " ", hint && /*#__PURE__*/React.createElement("span", {
      style: {
        color: "#64748b",
        fontWeight: 400,
        fontSize: 12
      }
    }, "\xB7 ", hint)), children);
  }
  function Chip({
    children
  }) {
    const [on, setOn] = React.useState(false);
    return /*#__PURE__*/React.createElement("button", {
      type: "button",
      onClick: () => setOn(!on),
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "7px 13px",
        borderRadius: 999,
        border: `1px solid ${on ? "var(--brand-primary)" : "#26314f"}`,
        background: on ? "color-mix(in srgb, var(--brand-primary) 16%, transparent)" : "transparent",
        color: on ? "#fff" : "#9fb0d0",
        fontSize: 13,
        cursor: "pointer"
      }
    }, on && /*#__PURE__*/React.createElement(Icon, {
      name: "check",
      size: 12
    }), children);
  }
  window.MarketingScreens = {
    Landing,
    GetStarted
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/marketing/screens.jsx", error: String((e && e.message) || e) }); }

// ui_kits/operator/screens.jsx
try { (() => {
/* Nexora — Operator console: lead pipeline, brand management (white-label
   control) and payout-holds review (the cautious money surface).
   Composes the design-system bundle. Exposes window.OperatorScreens. */
(function () {
  const NX = window.NexoraDesignSystem_985ae7;
  const {
    DataTable,
    StatusPill,
    Badge,
    Card,
    CardHeader,
    Button,
    Input,
    Select,
    FilterBar,
    Modal,
    EmptyState,
    Avatar,
    Icon,
    StatTile,
    MoneyConfirm
  } = NX;
  const money = n => "$" + n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });

  /* ---------- LEAD PIPELINE ---------- */
  const STAGES = [{
    key: "NEW",
    label: "New",
    count: 14
  }, {
    key: "CONTACTED",
    label: "Contacted",
    count: 9
  }, {
    key: "QUALIFIED",
    label: "Qualified",
    count: 6
  }, {
    key: "DEMO",
    label: "Demo",
    count: 4
  }, {
    key: "WON",
    label: "Won",
    count: 3
  }, {
    key: "LOST",
    label: "Lost",
    count: 5
  }];
  const stageTone = {
    New: "neutral",
    Contacted: "info",
    Qualified: "info",
    Demo: "warning",
    Won: "positive",
    Lost: "danger"
  };
  const leads = [{
    id: 1,
    name: "Acme Media Ltd",
    email: "ops@acmemedia.io",
    type: "Network",
    country: "🇰🇪 Kenya",
    stage: "Qualified",
    created: "2026-06-02"
  }, {
    id: 2,
    name: "Brightwave Ads",
    email: "deals@brightwave.co",
    type: "Advertiser",
    country: "🇳🇬 Nigeria",
    stage: "Demo",
    created: "2026-06-05"
  }, {
    id: 3,
    name: "Paul Otieno",
    email: "paul@trafficpros.com",
    type: "Solo",
    country: "🇿🇦 S. Africa",
    stage: "New",
    created: "2026-06-11"
  }, {
    id: 4,
    name: "Sahara Performance",
    email: "hello@saharaperf.com",
    type: "Network",
    country: "🇪🇬 Egypt",
    stage: "Won",
    created: "2026-05-21"
  }, {
    id: 5,
    name: "Lagos Lead Co",
    email: "biz@lagoslead.ng",
    type: "Advertiser",
    country: "🇳🇬 Nigeria",
    stage: "Contacted",
    created: "2026-06-09"
  }];
  function LeadPipeline() {
    const [active, setActive] = React.useState(null);
    const rows = active ? leads.filter(l => l.stage.toUpperCase() === active) : leads;
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        gap: 18
      }
    }, /*#__PURE__*/React.createElement("p", {
      style: {
        fontSize: 14,
        color: "var(--text-muted)",
        maxWidth: "70ch"
      }
    }, "The platform's own prospect pipeline \u2014 networks, brands and affiliates who requested a white-label setup. Move each lead through the stages as you work the deal."), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "grid",
        gridTemplateColumns: "repeat(6,1fr)",
        gap: 12
      }
    }, STAGES.map(s => {
      const on = active === s.key;
      return /*#__PURE__*/React.createElement("button", {
        key: s.key,
        onClick: () => setActive(on ? null : s.key),
        style: {
          textAlign: "center",
          padding: "14px 8px",
          background: "var(--surface-card)",
          border: `1px solid ${on ? "var(--brand-primary)" : "var(--border-default)"}`,
          borderRadius: "var(--radius-md)",
          cursor: "pointer",
          boxShadow: "var(--shadow-xs)"
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          fontSize: 26,
          fontWeight: 700,
          color: on ? "var(--brand-primary)" : "var(--text-strong)",
          fontVariantNumeric: "tabular-nums"
        }
      }, s.count), /*#__PURE__*/React.createElement("div", {
        style: {
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: ".05em",
          color: "var(--text-muted)",
          marginTop: 2
        }
      }, s.label));
    })), /*#__PURE__*/React.createElement(Card, {
      padding: "none"
    }, /*#__PURE__*/React.createElement(DataTable, {
      rowKey: "id",
      style: {
        border: "none",
        borderRadius: 0
      },
      empty: "No leads in this stage.",
      columns: [{
        key: "name",
        header: "Name",
        sortable: true,
        render: (v, r) => /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
          style: {
            fontWeight: 600,
            color: "var(--text-strong)"
          }
        }, v), /*#__PURE__*/React.createElement("div", {
          style: {
            fontSize: 12,
            color: "var(--text-muted)"
          }
        }, r.email))
      }, {
        key: "type",
        header: "Type",
        render: v => /*#__PURE__*/React.createElement(Badge, {
          tone: "neutral",
          outline: true
        }, v)
      }, {
        key: "country",
        header: "Country",
        muted: true
      }, {
        key: "stage",
        header: "Stage",
        render: v => /*#__PURE__*/React.createElement(StatusPill, {
          label: v,
          tone: stageTone[v],
          icon: null,
          dot: true
        })
      }, {
        key: "created",
        header: "Created",
        muted: true,
        mono: true
      }, {
        key: "id",
        header: "Manage",
        align: "right",
        render: (v, r) => /*#__PURE__*/React.createElement("div", {
          style: {
            display: "inline-flex",
            gap: 6,
            justifyContent: "flex-end"
          }
        }, r.stage === "Won" ? /*#__PURE__*/React.createElement(Button, {
          size: "sm",
          variant: "primary",
          iconLeft: "building"
        }, "Convert to brand") : /*#__PURE__*/React.createElement(Button, {
          size: "sm",
          variant: "secondary",
          iconRight: "chevron-right"
        }, "Open"))
      }],
      rows: rows
    })));
  }

  /* ---------- BRAND MANAGEMENT (white-label control) ---------- */
  const brands = [{
    name: "Nexora",
    domain: "cpa.cloudtrade.pro",
    primary: "#6366f1",
    secondary: "#4f46e5",
    affiliates: 1284,
    status: "Activated"
  }, {
    name: "CloudTrade Systems",
    domain: "partners.cloudtrade.pro",
    primary: "#0d9488",
    secondary: "#047857",
    affiliates: 612,
    status: "Activated"
  }, {
    name: "Sahara Performance",
    domain: "go.saharaperf.com",
    primary: "#ea580c",
    secondary: "#c2410c",
    affiliates: 88,
    status: "Pending"
  }, {
    name: "Brightwave",
    domain: "track.brightwave.co",
    primary: "#2563eb",
    secondary: "#1d4ed8",
    affiliates: 0,
    status: "Dormant"
  }];
  function BrandManagement({
    onCreate
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        gap: 18
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between"
      }
    }, /*#__PURE__*/React.createElement("p", {
      style: {
        fontSize: 14,
        color: "var(--text-muted)",
        maxWidth: "60ch"
      }
    }, "Every brand is a tenant of the same platform. Its two colors + logo cascade across the entire product \u2014 structure never changes."), /*#__PURE__*/React.createElement(Button, {
      iconLeft: "plus",
      onClick: onCreate
    }, "Create brand")), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "grid",
        gridTemplateColumns: "repeat(2,1fr)",
        gap: 16
      }
    }, brands.map(b => /*#__PURE__*/React.createElement(Card, {
      key: b.name,
      padding: "md",
      interactive: true
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 12
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 42,
        height: 42,
        borderRadius: "var(--radius-md)",
        background: b.primary,
        color: "#fff",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontWeight: 700,
        fontSize: 18
      }
    }, b.name[0]), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontWeight: 600,
        color: "var(--text-strong)"
      }
    }, b.name), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: "var(--text-muted)",
        fontFamily: "var(--font-mono)"
      }
    }, b.domain)), /*#__PURE__*/React.createElement(StatusPill, {
      status: b.status,
      size: "sm"
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 16,
        marginTop: 14,
        paddingTop: 14,
        borderTop: "1px solid var(--divider)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 5
      }
    }, /*#__PURE__*/React.createElement("span", {
      title: "Primary",
      style: {
        width: 22,
        height: 22,
        borderRadius: 6,
        background: b.primary,
        border: "1px solid var(--border-default)"
      }
    }), /*#__PURE__*/React.createElement("span", {
      title: "Secondary",
      style: {
        width: 22,
        height: 22,
        borderRadius: 6,
        background: b.secondary,
        border: "1px solid var(--border-default)"
      }
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: "var(--text-muted)"
      }
    }, /*#__PURE__*/React.createElement("strong", {
      style: {
        color: "var(--text-strong)",
        fontVariantNumeric: "tabular-nums"
      }
    }, b.affiliates.toLocaleString()), " affiliates"), /*#__PURE__*/React.createElement("div", {
      style: {
        marginLeft: "auto",
        display: "flex",
        gap: 6
      }
    }, /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "ghost",
      iconLeft: "settings"
    }, "Setup"), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "ghost",
      iconLeft: "external-link"
    }, "Visit")))))));
  }

  /* ---------- PAYOUT-HOLDS REVIEW (money surface) ---------- */
  const holds = [{
    id: 9182,
    affiliate: "Grace Wanjiru",
    method: "Crypto · USDT",
    amount: 2480.0,
    status: "Pending",
    reason: "Exceeds $2,000 auto-approve threshold",
    dest: "TQn9Y2khEsLJW1ChVWFMSMeRDow5f3Kd8a",
    until: "2026-06-20"
  }, {
    id: 9180,
    affiliate: "Paul Otieno",
    method: "PayPal",
    amount: 940.0,
    status: "Pending",
    reason: "First payout — cool-down hold",
    dest: "paul@trafficpros.com",
    until: "2026-06-19"
  }, {
    id: 9177,
    affiliate: "Lagos Lead Co",
    method: "Wise",
    amount: 5120.0,
    status: "Blocked",
    reason: "Daily velocity limit exceeded",
    dest: "Recipient #88231",
    until: "2026-06-21"
  }, {
    id: 9171,
    affiliate: "Sahara Performance",
    method: "Crypto · USDT",
    amount: 1310.0,
    status: "Pending",
    reason: "Anomaly: payout 3.2× 30-day avg",
    dest: "TXk2…9aB1",
    until: "2026-06-20"
  }];
  function PayoutHolds() {
    const [sel, setSel] = React.useState(null);
    const [done, setDone] = React.useState([]);
    const open = holds.find(h => h.id === sel);
    const list = holds.filter(h => !done.includes(h.id));
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        gap: 18
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
        padding: "12px 16px",
        background: "var(--status-warning-bg)",
        borderRadius: "var(--radius-md)"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "lock",
      size: 18,
      style: {
        color: "var(--status-warning-fg)",
        flexShrink: 0,
        marginTop: 1
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        color: "var(--text-body)"
      }
    }, /*#__PURE__*/React.createElement("strong", {
      style: {
        color: "var(--text-strong)"
      }
    }, "Money-control surface."), " These payouts were stopped before any funds moved. Every approve/deny is logged to the audit trail. Confirmations require a deliberate step.")), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "grid",
        gridTemplateColumns: "repeat(3,1fr)",
        gap: 16
      }
    }, /*#__PURE__*/React.createElement(StatTile, {
      label: "Held value",
      value: money(holds.reduce((a, h) => a + h.amount, 0)),
      icon: "dollar-sign",
      accent: true
    }), /*#__PURE__*/React.createElement(StatTile, {
      label: "Pending approval",
      value: String(holds.filter(h => h.status === "Pending").length),
      icon: "hourglass"
    }), /*#__PURE__*/React.createElement(StatTile, {
      label: "Velocity-blocked",
      value: String(holds.filter(h => h.status === "Blocked").length),
      icon: "ban"
    })), /*#__PURE__*/React.createElement(Card, {
      padding: "none"
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: "16px 20px",
        borderBottom: "1px solid var(--divider)"
      }
    }, /*#__PURE__*/React.createElement("h3", {
      style: {
        fontSize: "var(--text-lg)",
        fontWeight: 600
      }
    }, "Held / pending-approval payouts")), list.length === 0 ? /*#__PURE__*/React.createElement(EmptyState, {
      icon: "check-circle",
      title: "All clear",
      description: "No held payouts awaiting review.",
      compact: true
    }) : /*#__PURE__*/React.createElement(DataTable, {
      rowKey: "id",
      style: {
        border: "none",
        borderRadius: 0
      },
      columns: [{
        key: "id",
        header: "#",
        muted: true,
        mono: true,
        width: 64
      }, {
        key: "affiliate",
        header: "Affiliate",
        sortable: true,
        render: v => /*#__PURE__*/React.createElement("div", {
          style: {
            display: "flex",
            alignItems: "center",
            gap: 8
          }
        }, /*#__PURE__*/React.createElement(Avatar, {
          name: v,
          size: "xs"
        }), v)
      }, {
        key: "method",
        header: "Method",
        muted: true
      }, {
        key: "reason",
        header: "Reason held",
        muted: true,
        wrap: true
      }, {
        key: "status",
        header: "Status",
        render: v => /*#__PURE__*/React.createElement(StatusPill, {
          status: v === "Pending" ? "Pending" : "Blocked",
          label: v === "Pending" ? "Pending approval" : "Blocked",
          size: "sm"
        })
      }, {
        key: "amount",
        header: "Amount",
        align: "right",
        mono: true,
        sortable: true,
        render: v => money(v)
      }, {
        key: "_a",
        header: "",
        align: "right",
        render: (v, r) => r.status === "Pending" ? /*#__PURE__*/React.createElement(Button, {
          size: "sm",
          iconLeft: "shield-check",
          onClick: () => setSel(r.id)
        }, "Review") : /*#__PURE__*/React.createElement("span", {
          style: {
            fontSize: 12,
            color: "var(--text-faint)"
          }
        }, "limit-blocked")
      }],
      rows: list
    })), open && /*#__PURE__*/React.createElement("div", {
      style: {
        position: "fixed",
        inset: 0,
        zIndex: 50,
        background: "var(--surface-overlay)",
        backdropFilter: "blur(2px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24
      },
      onClick: () => setSel(null)
    }, /*#__PURE__*/React.createElement("div", {
      onClick: e => e.stopPropagation()
    }, /*#__PURE__*/React.createElement(MoneyConfirm, {
      intent: "approve",
      amount: money(open.amount),
      destinationLabel: open.method,
      destination: open.dest,
      rows: [{
        label: "Affiliate",
        value: open.affiliate
      }, {
        label: "Request #",
        value: String(open.id),
        mono: true
      }, {
        label: "Hold until",
        value: open.until,
        mono: true
      }],
      reasonHeld: open.reason,
      audit: [{
        actor: "System",
        action: "flagged: " + open.reason,
        at: "2026-06-17 06:14 UTC"
      }, {
        actor: "controls",
        action: "placed on hold",
        at: "2026-06-17 06:14 UTC"
      }],
      confirmWord: "APPROVE",
      onCancel: () => setSel(null),
      onConfirm: () => {
        setDone([...done, open.id]);
        setSel(null);
      }
    }))));
  }
  window.OperatorScreens = {
    LeadPipeline,
    BrandManagement,
    PayoutHolds
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/operator/screens.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Button = __ds_scope.Button;

__ds_ns.IconButton = __ds_scope.IconButton;

__ds_ns.DataTable = __ds_scope.DataTable;

__ds_ns.FilterBar = __ds_scope.FilterBar;

__ds_ns.StatTile = __ds_scope.StatTile;

__ds_ns.Avatar = __ds_scope.Avatar;

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Card = __ds_scope.Card;

__ds_ns.CardHeader = __ds_scope.CardHeader;

__ds_ns.StatusPill = __ds_scope.StatusPill;

__ds_ns.EmptyState = __ds_scope.EmptyState;

__ds_ns.ImpersonationBanner = __ds_scope.ImpersonationBanner;

__ds_ns.Modal = __ds_scope.Modal;

__ds_ns.MoneyConfirm = __ds_scope.MoneyConfirm;

__ds_ns.Toast = __ds_scope.Toast;

__ds_ns.ToastViewport = __ds_scope.ToastViewport;

__ds_ns.Checkbox = __ds_scope.Checkbox;

__ds_ns.Input = __ds_scope.Input;

__ds_ns.Select = __ds_scope.Select;

__ds_ns.Icon = __ds_scope.Icon;

__ds_ns.Sidebar = __ds_scope.Sidebar;

__ds_ns.Topbar = __ds_scope.Topbar;

})();
