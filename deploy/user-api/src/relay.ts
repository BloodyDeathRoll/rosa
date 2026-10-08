// The push-api write routes behind a per-IP rate limit (OPEN-ITEMS 33a, 2026-10-08).
//
//   POST   /push/contact   -> rosa-push /api/contact    Contact Us + spot reports
//   POST   /push/feedback  -> rosa-push /api/feedback   the 👍👎 drop-box (app + service worker)
//   POST   /push/sub       -> rosa-push /api/sub        register / update a push device
//   DELETE /push/sub       -> rosa-push /api/sub        forget a push device
//
// rosa-push is a Vercel project and its plan cannot rate-limit (401 on `vercel firewall
// rules add --action rate_limit`), so these three anonymous writes were unbounded per
// client. Here each gets a Workers Rate Limiting budget per client IP, then is forwarded
// server-to-server with `x-relay-secret`; rosa-push refuses the three routes without it,
// so the limit cannot be walked around by calling rosa-push directly. The body is
// forwarded as-is: rosa-push stays the one place that validates it.
//
// Its own module so `node --test` can import it (index.ts has syntax Node's type
// stripping does not run).

export interface RelayEnv {
  PUSH_RELAY_SECRET?: string; // secret, shared with the rosa-push project env
  PUSH_API_ORIGIN?: string; // [vars]; default below
  CONTACT_LIMIT?: RateLimit; // wrangler.toml [[ratelimits]]; absent in tests
  FEEDBACK_LIMIT?: RateLimit;
  SUB_LIMIT?: RateLimit;
}

type LimitName = "CONTACT_LIMIT" | "FEEDBACK_LIMIT" | "SUB_LIMIT";

export const RELAY_ROUTES: Record<string, { target: string; methods: string[]; limit: LimitName }> = {
  "/push/contact": { target: "/api/contact", methods: ["POST"], limit: "CONTACT_LIMIT" },
  "/push/feedback": { target: "/api/feedback", methods: ["POST"], limit: "FEEDBACK_LIMIT" },
  "/push/sub": { target: "/api/sub", methods: ["POST", "DELETE"], limit: "SUB_LIMIT" },
};

const DEFAULT_PUSH_API = "https://rosa-push.vercel.app";
// contact.js caps a message at 2000 chars; the rest of the row is small. Generous on purpose.
export const MAX_RELAY_BYTES = 8192;

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

/** The relay's answer for `path`, or null when `path` is not a relay route. */
export async function relay(
  req: Request,
  env: RelayEnv,
  path: string,
  fetchImpl: typeof fetch = fetch,
): Promise<Response | null> {
  const r = RELAY_ROUTES[path];
  if (!r) return null;
  if (!r.methods.includes(req.method)) return reply(405, { error: "method" });

  // a missing client IP shares one bucket rather than skipping the limit
  const limit = env[r.limit];
  if (limit) {
    const { success } = await limit.limit({ key: req.headers.get("cf-connecting-ip") ?? "unknown" });
    if (!success) return reply(429, { error: "rate" });
  }
  if (!env.PUSH_RELAY_SECRET) return reply(503, { error: "relay" });

  if (Number(req.headers.get("Content-Length") ?? "0") > MAX_RELAY_BYTES) return reply(413, { error: "size" });
  const body = await req.text();
  if (body.length > MAX_RELAY_BYTES) return reply(413, { error: "size" });

  let upstream: Response;
  try {
    upstream = await fetchImpl(`${env.PUSH_API_ORIGIN || DEFAULT_PUSH_API}${r.target}`, {
      method: req.method,
      headers: { "Content-Type": "application/json", "x-relay-secret": env.PUSH_RELAY_SECRET },
      body,
    });
  } catch {
    return reply(502, { error: "upstream" });
  }
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      "Cache-Control": "no-store",
    },
  });
}
