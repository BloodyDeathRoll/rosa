// The x-admin-secret check shared by subs.js and feedback.js. Constant-time
// (audit 2026-09-11): `!==` on a secret returns sooner the earlier the first
// wrong byte is. Both sides are hashed first so their lengths match, which
// timingSafeEqual requires. The leading underscore keeps Vercel from serving
// this file as a route.

import { createHash, timingSafeEqual } from "node:crypto";

const digest = (s) => createHash("sha256").update(s).digest();

export function adminOk(req) {
  const secret = process.env.PUSH_ADMIN_SECRET;
  const given = req.headers["x-admin-secret"];
  if (!secret || typeof given !== "string") return false;
  return timingSafeEqual(digest(given), digest(secret));
}
