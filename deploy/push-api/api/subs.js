// Admin surface for the pipeline VM's sender (rosa-pipeline notify).
// GET    → every stored subscription record, JSON array
// DELETE {endpoint} → prune a dead subscription (sender saw 404/410)
// Auth: x-admin-secret header must equal PUSH_ADMIN_SECRET. No CORS — this is
// server-to-server only.

import { del, get, list } from "@vercel/blob";
import { createHash } from "node:crypto";

export default async function handler(req, res) {
  const secret = process.env.PUSH_ADMIN_SECRET;
  if (!secret || req.headers["x-admin-secret"] !== secret) {
    return res.status(401).json({ error: "auth" });
  }

  if (req.method === "GET") {
    const records = [];
    let cursor;
    do {
      const page = await list({ prefix: "push/subs/", cursor, limit: 1000 });
      cursor = page.cursor;
      const bodies = await Promise.all(
        page.blobs.map(async (b) => {
          try {
            const r = await get(b.pathname, { access: "private", useCache: false });
            return r?.stream ? await new Response(r.stream).json() : null;
          } catch {
            return null;
          }
        })
      );
      records.push(...bodies.filter(Boolean));
    } while (cursor);
    res.setHeader("Cache-Control", "no-store");
    return res.status(200).json(records);
  }

  if (req.method === "DELETE") {
    const endpoint = req.body?.endpoint;
    if (typeof endpoint !== "string") return res.status(400).json({ error: "bad endpoint" });
    await del(`push/subs/${createHash("sha256").update(endpoint).digest("hex")}.json`);
    return res.status(200).json({ ok: true });
  }

  return res.status(405).json({ error: "method" });
}
