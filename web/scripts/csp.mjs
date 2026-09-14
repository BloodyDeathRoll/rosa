// Writes .vercel/output/config.json from vercel-output.json plus a
// Content-Security-Policy-Report-Only header (audit 2026-09-11, proposals item 3).
// Report-only: nothing is blocked; violations POST to push-api /api/csp and land in
// its function logs. The inline <script>s in index.html are allowed by hash, taken
// from the built dist/index.html here, so editing one can never leave a stale hash.
// Enforce (drop "-Report-Only") after a clean week of reports.
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

const html = readFileSync("dist/index.html", "utf8");
const hashes = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map(
  (m) => `'sha256-${createHash("sha256").update(m[1]).digest("base64")}'`,
);

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
const csp = Object.entries(policy)
  .map(([k, v]) => `${k} ${v.join(" ")}`)
  .join("; ");

const cfg = JSON.parse(readFileSync("vercel-output.json", "utf8"));
// the site-wide headers route excludes /widget/ (the embeddable card carries its own)
const site = cfg.routes.find((r) => r.src === "^/(?!widget/)(.*)$" && r.continue && r.headers);
if (!site) throw new Error("vercel-output.json: no site-wide headers route to carry the CSP");
site.headers["Content-Security-Policy-Report-Only"] = csp;
writeFileSync(".vercel/output/config.json", JSON.stringify(cfg, null, 2) + "\n");
console.log(`csp: report-only, ${hashes.length} inline script hash(es)`);
