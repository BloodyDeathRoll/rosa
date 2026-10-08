// The x-relay-secret check for the three public write routes (OPEN-ITEMS 33a, 2026-10-08).
// rosa-push's plan cannot rate-limit, so /api/contact, /api/feedback (POST) and /api/sub
// are reached through the user-api Worker (deploy/user-api/src/relay.ts), which limits
// each client IP and forwards here with this header. Refusing a write without it is what
// stops a caller walking around the limit by posting here directly.
//
// Enforced only while PUSH_RELAY_SECRET is set on this project (the Worker holds the same
// value). Constant-time like _admin.js; the leading underscore keeps Vercel from serving
// this file as a route.
//
// GRACE: an installed app opened after the 2026-10-08 web deploy can run its old,
// precached bundle for one more session, and a phone's service worker (push-sw.js, the
// lock-screen 👍👎) refreshes only on its next update check. Both still post here
// directly, so sub and feedback accept a direct write until GRACE_UNTIL. Contact needs no
// grace: the old bundle also mails the message from the browser, so nothing is lost.

import { createHash, timingSafeEqual } from "node:crypto";

export const GRACE_UNTIL = Date.parse("2026-10-22T00:00:00Z");

const digest = (s) => createHash("sha256").update(s).digest();

export function relayOk(req, { grace = false, now = Date.now() } = {}) {
  const secret = process.env.PUSH_RELAY_SECRET;
  if (!secret) return true;
  const given = req.headers["x-relay-secret"];
  if (typeof given === "string" && timingSafeEqual(digest(given), digest(secret))) return true;
  return grace && now < GRACE_UNTIL;
}
