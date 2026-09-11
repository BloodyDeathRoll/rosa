// CSP violation reports from the PWA (Content-Security-Policy-Report-Only, audit
// 2026-09-11; the policy is built by web/scripts/csp.mjs). Nothing is stored: each
// report is one trimmed log line in the rosa-push function logs, read before the
// policy is enforced. Browsers send reports no-cors, so there is no CORS here.

const MAX_BYTES = 8192;
const cut = (v) => (typeof v === "string" ? v.slice(0, 200) : undefined);

async function rawBody(req) {
  const chunks = [];
  let n = 0;
  for await (const c of req) {
    n += c.length;
    if (n > MAX_BYTES) return null;
    chunks.push(c);
  }
  return Buffer.concat(chunks).toString("utf8");
}

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).end();
  if (Number(req.headers?.["content-length"] ?? 0) > MAX_BYTES) return res.status(413).end();
  // Vercel parses JSON bodies; application/csp-report arrives as a string or Buffer
  let body = req.body ?? (await rawBody(req));
  if (Buffer.isBuffer(body)) body = body.toString("utf8");
  if (body === null || (typeof body === "string" && body.length > MAX_BYTES)) return res.status(413).end();
  if (typeof body === "string") {
    try {
      body = JSON.parse(body);
    } catch {
      return res.status(400).end();
    }
  }
  // a chunked request has no content-length, and Vercel may already have parsed it
  if (JSON.stringify(body ?? null).length > MAX_BYTES) return res.status(413).end();
  const r = body?.["csp-report"];
  if (!r || typeof r !== "object") return res.status(400).end();
  console.log(
    "csp",
    JSON.stringify({
      doc: cut(r["document-uri"]),
      directive: cut(r["effective-directive"] ?? r["violated-directive"]),
      blocked: cut(r["blocked-uri"]),
      source: cut(r["source-file"]),
      line: Number.isInteger(r["line-number"]) ? r["line-number"] : undefined,
    }),
  );
  return res.status(204).end();
}
