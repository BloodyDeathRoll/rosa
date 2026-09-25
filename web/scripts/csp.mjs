// Writes .vercel/output/config.json from vercel-output.json plus the
// Content-Security-Policy headers (audit 2026-09-11, proposals item 3). ENFORCED since
// 2026-09-25 (Dream review): two weeks report-only, then a headless crawl of the live
// site (map, spot + cam player, charts, search, settings, account, widget) logged zero
// violations; push-api keeps no logs to read. Violations still POST to push-api
// /api/csp. Inline <script>s are allowed by hash, taken from the built dist/ HTML here,
// so editing one can never leave a stale hash.
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";

const env = Object.fromEntries(
  readFileSync(".env.production", "utf8")
    .split("\n")
    .map((l) => l.match(/^(VITE_\w+)=(.*)$/))
    .filter(Boolean)
    .map((m) => [m[1], m[2].trim()]),
);
const origin = (k) => {
  if (!env[k]) throw new Error(`csp: ${k} is missing from .env.production`);
  return new URL(env[k]).origin;
};

const inlineHashes = (file) =>
  [...readFileSync(file, "utf8").matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map(
    (m) => `'sha256-${createHash("sha256").update(m[1]).digest("base64")}'`,
  );
const hashes = inlineHashes("dist/index.html");

const GA = ["https://www.googletagmanager.com", "https://*.google-analytics.com", "https://*.analytics.google.com"];
const policy = {
  "default-src": ["'self'"],
  "script-src": ["'self'", ...hashes, "https://accounts.google.com/gsi/client", "https://www.googletagmanager.com"],
  "style-src": ["'self'", "'unsafe-inline'", "https://accounts.google.com/gsi/style"],
  "img-src": [
    "'self'",
    "data:",
    "blob:",
    "https://i.ytimg.com", // cam thumbnails
    "https://server.arcgisonline.com", // satellite cards
    "https://tiles.openfreemap.org",
    "https://*.googleusercontent.com", // account avatar
    ...GA,
  ],
  "font-src": ["'self'", "data:"],
  "connect-src": [
    "'self'",
    origin("VITE_DATA_BASE"),
    origin("VITE_PUSH_API"),
    origin("VITE_USER_API"),
    "https://tiles.openfreemap.org",
    "https://accounts.google.com/gsi/",
    ...GA,
  ],
  "frame-src": ["https://accounts.google.com/gsi/", "https://www.youtube-nocookie.com"],
  "worker-src": ["'self'", "blob:"],
  "manifest-src": ["'self'"],
  "object-src": ["'none'"],
  "base-uri": ["'self'"],
  "form-action": ["'self'"],
  "frame-ancestors": ["'none'"],
  "report-uri": [`${origin("VITE_PUSH_API")}/api/csp`],
};
const serialize = (p) =>
  Object.entries(p)
    .map(([k, v]) => `${k} ${v.join(" ")}`)
    .join("; ");
const csp = serialize(policy);

// The embeddable card (public/widget/): framed by anyone, so frame-ancestors stays *.
// It builds its DOM with innerHTML from the data CDN's JSON; this makes a slip in an
// escape non-executable - its own inline script, that CDN, the Esri tiles, Inter.
const widgetHashes = inlineHashes("dist/widget/index.html");
const widget = serialize({
  "default-src": ["'none'"],
  "script-src": widgetHashes,
  "style-src": ["'unsafe-inline'", "https://fonts.googleapis.com"],
  "font-src": ["https://fonts.gstatic.com"],
  "img-src": ["'self'", "https://server.arcgisonline.com"],
  "connect-src": [origin("VITE_DATA_BASE")],
  "base-uri": ["'none'"],
  "form-action": ["'none'"],
  "frame-ancestors": ["*"],
  "report-uri": [`${origin("VITE_PUSH_API")}/api/csp`],
});

const cfg = JSON.parse(readFileSync("vercel-output.json", "utf8"));
// the site-wide headers route excludes /widget/ (the embeddable card carries its own)
const site = cfg.routes.find((r) => r.src === "^/(?!widget/)(.*)$" && r.continue && r.headers);
if (!site) throw new Error("vercel-output.json: no site-wide headers route to carry the CSP");
site.headers["Content-Security-Policy"] = csp;
const embed = cfg.routes.find((r) => r.src === "^/widget/(.*)$" && r.continue && r.headers);
if (!embed) throw new Error("vercel-output.json: no /widget/ headers route to carry its CSP");
if (widgetHashes.length !== 1) throw new Error(`csp: expected 1 inline script in the widget, found ${widgetHashes.length}`);
embed.headers["Content-Security-Policy"] = widget;
writeFileSync(".vercel/output/config.json", JSON.stringify(cfg, null, 2) + "\n");
console.log(`csp: enforced, ${hashes.length} inline script hash(es) + widget`);
