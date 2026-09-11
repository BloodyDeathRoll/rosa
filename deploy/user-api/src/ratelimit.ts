// POST /auth/google is capped per client IP (audit 2026-09-11) - the one anonymous
// route that does real work (a Google token exchange and a D1 write). The binding is
// wrangler.toml [[ratelimits]] SIGNIN_LIMIT; without it (tests, a bare `wrangler dev`)
// sign-in is unlimited. Its own module so `node --test` can import it (index.ts has
// syntax Node's type stripping does not run).

export async function signInAllowed(req: Request, env: { SIGNIN_LIMIT?: RateLimit }): Promise<boolean> {
  if (!env.SIGNIN_LIMIT) return true;
  const { success } = await env.SIGNIN_LIMIT.limit({ key: req.headers.get("cf-connecting-ip") ?? "unknown" });
  return success;
}
