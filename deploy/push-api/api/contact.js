// Contact Us drop-box: POST (app origins) {message, page?, ua?} → emailed to the
// maintainer via Resend and stored as a private blob either way, so a message is
// never lost when the mail key is missing or Resend is down.
//
// Env: RESEND_API_KEY (Resend), CONTACT_TO (defaults to the maintainer's address),
//      CONTACT_FROM (defaults to Resend's onboarding sender, which only delivers to
//      the Resend account owner - set a verified-domain sender for anything else).

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

async function mail(row) {
  const key = process.env.RESEND_API_KEY;
  if (!key) return { mailed: false, why: "no RESEND_API_KEY" };
  const text = `${row.message}\n\n---\nreceived: ${row.received}\npage: ${row.page}\nua: ${row.ua}`;
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      from: CONTACT_FROM,
      to: [CONTACT_TO],
      subject: "Rosa feedback",
      text,
    }),
  });
  if (!r.ok) return { mailed: false, why: `resend ${r.status}` };
  return { mailed: true };
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
  return res.status(200).json({ ok: true, mailed: mailed.mailed });
}
