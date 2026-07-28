// Rosa push-subscription endpoint (the app's only write surface).
// POST  {endpoint, keys:{p256dh,auth}, spots:[ids]} → upsert this device
// DELETE {endpoint}                                 → forget this device
//
// Records live in a PRIVATE Vercel Blob store at push/subs/<sha256(endpoint)>.json
// - readable only with the store token (the admin surface in subs.js), never via
// a public URL.

import { del, put } from "@vercel/blob";
import { createHash } from "node:crypto";

const ALLOWED_ORIGINS = new Set([
  "https://rosa-rust.vercel.app",
  "https://rosa-demo.vercel.app", // look-and-feel demo deploys (synthetic events)
  "http://localhost:5173",
  "http://localhost:4173",
]);

const MAX_SPOTS = 200;
const SPOT_ID = /^[\w-]{1,64}$/;

function cors(req, res) {
  const origin = req.headers.origin;
  if (origin && ALLOWED_ORIGINS.has(origin)) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Vary", "Origin");
    res.setHeader("Access-Control-Allow-Methods", "POST, DELETE, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  }
}

const pathOf = (endpoint) =>
  `push/subs/${createHash("sha256").update(endpoint).digest("hex")}.json`;

export default async function handler(req, res) {
  cors(req, res);
  if (req.method === "OPTIONS") return res.status(204).end();
  const body = req.body ?? {};
  const endpoint = body.endpoint;
  if (typeof endpoint !== "string" || !endpoint.startsWith("https://") || endpoint.length > 1024) {
    return res.status(400).json({ error: "bad endpoint" });
  }

  if (req.method === "DELETE") {
    await del(pathOf(endpoint));
    return res.status(200).json({ ok: true });
  }

  if (req.method === "POST") {
    const keys = body.keys ?? {};
    const spots = body.spots ?? [];
    // nearest spot id, never coordinates - enough for the sender to keep the
    // evening ask in the user's own region, and to have something to ask about
    // when nothing is favorited. Null whenever location is unknown/denied.
    const home = body.home ?? null;
    if (
      typeof keys.p256dh !== "string" ||
      typeof keys.auth !== "string" ||
      keys.p256dh.length > 256 ||
      keys.auth.length > 64 ||
      !Array.isArray(spots) ||
      spots.length > MAX_SPOTS ||
      spots.some((s) => typeof s !== "string" || !SPOT_ID.test(s)) ||
      (home !== null && (typeof home !== "string" || !SPOT_ID.test(home)))
    ) {
      return res.status(400).json({ error: "bad subscription" });
    }
    const record = {
      endpoint,
      keys: { p256dh: keys.p256dh, auth: keys.auth },
      spots,
      home,
      // "Spot feedback" Profile toggle - the sender skips the evening 👍👎
      // ask for subs that turned it off
      feedback: body.feedback !== false,
      updated: new Date().toISOString(),
    };
    await put(pathOf(endpoint), JSON.stringify(record), {
      access: "private",
      contentType: "application/json",
      addRandomSuffix: false,
      allowOverwrite: true,
    });
    return res.status(200).json({ ok: true });
  }

  return res.status(405).json({ error: "method" });
}
