// Contact Us drop-box: POST (app origins) {message, page?, ua?, email?, name?} → emailed to the
// maintainer and stored as a private blob either way, so a message is never lost when
// the mail hop fails.
//
// TWO mail paths, tried in order:
//   1. Resend, when RESEND_API_KEY is set. Nothing sets it today.
//   2. FormSubmit (https://formsubmit.co), which needs NO key or account - just a
//      one-time "Activate Form" click by the recipient. This is the live path, added
//      2026-09-03 after the page shipped storing messages and mailing none of them
//      because the Resend key was never created.
//
// Env: CONTACT_TO (defaults to the maintainer's address), RESEND_API_KEY and
//      CONTACT_FROM (optional, only for path 1).

import { put } from "@vercel/blob";
import { randomUUID } from "node:crypto";
import { relayOk } from "./_relay.js";

const ALLOWED_ORIGINS = new Set([
  "https://rosa.surf",
  "https://www.rosa.surf",
  "https://rosa-rust.vercel.app", // legacy origin, installed PWAs still live here
  "https://rosa-demo.vercel.app",
  "http://localhost:5173",
  "http://localhost:4173",
]);

const MAX_MESSAGE = 2000;
const CONTACT_TO = process.env.CONTACT_TO || "info@rosa.surf";
const CONTACT_FROM = process.env.CONTACT_FROM || "Rosa <onboarding@resend.dev>";

function cors(req, res) {
  const origin = req.headers.origin;
  if (origin && ALLOWED_ORIGINS.has(origin)) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Vary", "Origin");
    res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  }
}

function bodyText(row) {
  const from = row.email ? `\nfrom: ${row.name ? `${row.name} <${row.email}>` : row.email}` : "";
  return `${row.message}\n\n---\nreceived: ${row.received}${from}\npage: ${row.page}\nua: ${row.ua}`;
}

async function mailViaResend(row) {
  const key = process.env.RESEND_API_KEY;
  if (!key) return { mailed: false, why: "no RESEND_API_KEY" };
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      from: CONTACT_FROM,
      to: [CONTACT_TO],
      subject: row.kind === "report" ? `Rosa report: ${row.spot ?? "spot"}` : "Rosa feedback",
      text: bodyText(row),
      ...(row.email ? { reply_to: row.email } : {}),
    }),
  });
  if (!r.ok) return { mailed: false, why: `resend ${r.status}` };
  return { mailed: true, via: "resend" };
}

// FormSubmit rejects a request with no Origin/Referer ("open this page through a web
// server"), so both are sent explicitly - this call comes from a serverless function,
// not a browser. `_captcha: false` keeps it a plain relay.
async function mailViaFormSubmit(row) {
  const r = await fetch(`https://formsubmit.co/ajax/${encodeURIComponent(CONTACT_TO)}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      Origin: "https://rosa-push.vercel.app",
      Referer: "https://rosa-push.vercel.app/",
      // without a User-Agent FormSubmit answers 403 to a serverless caller (it 200s
      // for curl, which sends one) - measured 2026-09-03, this line is load-bearing
      "User-Agent": "rosa-push/1.0 (+https://rosa.surf)",
    },
    body: JSON.stringify({
      _subject: row.kind === "report" ? `Rosa report: ${row.spot ?? "spot"}` : "Rosa feedback",
      _captcha: "false",
      // `email`, not `_replyto`: FormSubmit ignores `_replyto` on the ajax endpoint and
      // leaves Reply-To pointing at itself (measured 2026-09-10).
      ...(row.email ? { email: row.email, name: row.name ?? "" } : {}),
      message: bodyText(row),
    }),
  });
  let out = {};
  try {
    out = await r.json();
  } catch {
    return { mailed: false, why: `formsubmit ${r.status} (unparseable)` };
  }
  if (!r.ok || String(out.success) !== "true") {
    return { mailed: false, why: `formsubmit: ${out.message || r.status}` };
  }
  return { mailed: true, via: "formsubmit" };
}

async function mail(row) {
  const viaResend = await mailViaResend(row);
  if (viaResend.mailed) return viaResend;
  const viaForm = await mailViaFormSubmit(row);
  if (viaForm.mailed) return viaForm;
  return { mailed: false, why: `${viaResend.why}; ${viaForm.why}` };
}

export default async function handler(req, res) {
  cors(req, res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") return res.status(405).json({ error: "method" });
  // only through the user-api Worker's rate-limited relay (_relay.js, OPEN-ITEMS 33a)
  if (!relayOk(req)) return res.status(403).json({ error: "relay" });

  const b = req.body ?? {};
  const message = typeof b.message === "string" ? b.message.trim() : "";
  if (!message || message.length > MAX_MESSAGE) {
    return res.status(400).json({ error: "bad message" });
  }
  const row = {
    message,
    // "report" rows carry the spot and the reader's chosen issue, so a human review can
    // group them per spot without re-parsing the body
    kind: b.kind === "report" ? "report" : "feedback",
    reason: typeof b.reason === "string" ? b.reason.slice(0, 80) : null,
    spot: typeof b.spot === "string" && /^[\w-]{1,64}$/.test(b.spot) ? b.spot : null,
    // the signed-in sender (Google account email), when there is one - so a report
    // can be answered. Never required; the app sends null when signed out.
    email:
      typeof b.email === "string" && b.email.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(b.email)
        ? b.email
        : null,
    name: typeof b.name === "string" ? b.name.slice(0, 200) : null,
    page: typeof b.page === "string" ? b.page.slice(0, 120) : "",
    ua: typeof b.ua === "string" ? b.ua.slice(0, 300) : "",
    received: new Date().toISOString(),
  };

  // the blob is the record; the email is the notification
  await put(`contact/${Date.now()}-${randomUUID()}.json`, JSON.stringify(row), {
    access: "private",
    contentType: "application/json",
    addRandomSuffix: false,
  });
  let mailed = { mailed: false, why: "error" };
  try {
    mailed = await mail(row);
  } catch (e) {
    mailed = { mailed: false, why: String(e) };
  }
  if (!mailed.mailed) console.warn("contact: stored but not mailed:", mailed.why);
  return res.status(200).json({ ok: true, mailed: mailed.mailed, via: mailed.via ?? null });
}
