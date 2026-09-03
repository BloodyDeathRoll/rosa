// Contact Us drop-box: POST (app origins) {message, page?, ua?} → emailed to the
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

const ALLOWED_ORIGINS = new Set([
  "https://rosa-rust.vercel.app",
  "https://rosa-demo.vercel.app",
  "http://localhost:5173",
  "http://localhost:4173",
]);

const MAX_MESSAGE = 2000;
const CONTACT_TO = process.env.CONTACT_TO || "einhanamer@gmail.com";
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
  return `${row.message}\n\n---\nreceived: ${row.received}\npage: ${row.page}\nua: ${row.ua}`;
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
      subject: "Rosa feedback",
      text: bodyText(row),
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
      "User-Agent": "rosa-push/1.0 (+https://rosa-rust.vercel.app)",
    },
    body: JSON.stringify({
      _subject: "Rosa feedback",
      _captcha: "false",
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

  const b = req.body ?? {};
  const message = typeof b.message === "string" ? b.message.trim() : "";
  if (!message || message.length > MAX_MESSAGE) {
    return res.status(400).json({ error: "bad message" });
  }
  const row = {
    message,
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
