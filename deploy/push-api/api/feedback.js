// Crowd 👍👎 feedback drop-box (the calibration truth no buoy can give).
// POST   (via the user-api relay) one FeedbackRecord-shaped row → stored as a private blob
// GET    (x-admin-secret) all rows, each with its blob `id`
// DELETE (x-admin-secret) {ids} → prune rows the VM has merged into its store
//
// The VM's `rosa-pipeline notify` pulls + prunes each cycle, appending rows to
// data/verify/feedback/feedback.jsonl where `feedback --report` already reads.

import { del, get, list, put } from "@vercel/blob";
import { randomUUID } from "node:crypto";
import { adminOk } from "./_admin.js";
import { relayOk } from "./_relay.js";

const ALLOWED_ORIGINS = new Set([
  "https://rosa.surf",
  "https://www.rosa.surf",
  "https://rosa-rust.vercel.app", // legacy origin, installed PWAs still live here
  "https://rosa-demo.vercel.app",
  "http://localhost:5173",
  "http://localhost:4173",
]);

const SPOT_ID = /^[\w-]{1,64}$/;

function cors(req, res) {
  const origin = req.headers.origin;
  if (origin && ALLOWED_ORIGINS.has(origin)) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Vary", "Origin");
    res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  }
}

export default async function handler(req, res) {
  cors(req, res);
  if (req.method === "OPTIONS") return res.status(204).end();

  if (req.method === "POST") {
    // only through the user-api Worker's rate-limited relay (_relay.js, OPEN-ITEMS 33a);
    // direct posts from not-yet-updated service workers pass until GRACE_UNTIL
    if (!relayOk(req, { grace: true })) return res.status(403).json({ error: "relay" });
    const b = req.body ?? {};
    const predicted = b.predicted && typeof b.predicted === "object" ? b.predicted : {};
    if (
      typeof b.spot !== "string" ||
      !SPOT_ID.test(b.spot) ||
      (b.verdict !== "up" && b.verdict !== "down") ||
      typeof b.at !== "string" ||
      b.at.length > 40 ||
      JSON.stringify(predicted).length > 2000
    ) {
      return res.status(400).json({ error: "bad feedback" });
    }
    const row = {
      spot: b.spot,
      at: b.at,
      verdict: b.verdict,
      predicted,
      observed: {},
      source: b.source === "push" ? "push" : "web",
      received: new Date().toISOString(),
    };
    await put(`feedback/${Date.now()}-${randomUUID()}.json`, JSON.stringify(row), {
      access: "private",
      contentType: "application/json",
      addRandomSuffix: false,
    });
    return res.status(200).json({ ok: true });
  }

  // admin surface below - server-to-server only
  if (!adminOk(req)) {
    return res.status(401).json({ error: "auth" });
  }

  if (req.method === "GET") {
    const rows = [];
    let cursor;
    do {
      const page = await list({ prefix: "feedback/", cursor, limit: 1000 });
      cursor = page.cursor;
      const bodies = await Promise.all(
        page.blobs.map(async (b) => {
          try {
            const r = await get(b.pathname, { access: "private", useCache: false });
            if (!r?.stream) return null;
            return { id: b.pathname, ...(await new Response(r.stream).json()) };
          } catch {
            return null;
          }
        })
      );
      rows.push(...bodies.filter(Boolean));
    } while (cursor);
    res.setHeader("Cache-Control", "no-store");
    return res.status(200).json(rows);
  }

  if (req.method === "DELETE") {
    const ids = req.body?.ids;
    if (!Array.isArray(ids) || ids.some((i) => typeof i !== "string" || !i.startsWith("feedback/"))) {
      return res.status(400).json({ error: "bad ids" });
    }
    if (ids.length > 0) await del(ids);
    return res.status(200).json({ ok: true });
  }

  return res.status(405).json({ error: "method" });
}
