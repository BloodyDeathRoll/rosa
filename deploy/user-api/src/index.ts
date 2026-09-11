// Rosa user API - Google sign-in + per-user favorites. Cloudflare Worker + D1.
//
//   POST   /auth/google   {code}         -> {token, profile, favorites}   sign in / sign up
//                         (Google OAuth one-time code from the browser's account-chooser
//                          popup; `{credential}` - a GIS ID token - is accepted too)
//   GET    /me                           -> {profile, favorites}
//   PUT    /me/favorites  {favorites}    -> {favorites}                   full list, server is truth
//   POST   /auth/logout                  -> {ok}                          revokes EVERY session
//   DELETE /me                           -> {ok}                          the account and its data
//   GET    /admin/stats   x-admin-secret -> counts                        "how many users"
//
// Authenticated routes take `Authorization: Bearer <session>` (see session.ts).
// The user key is Google's `sub`, never anything of ours, so the rows move to any
// other backend without re-linking users. Nothing here is on the forecast read
// path - that stays static (CLAUDE.md principle 2).

import { TokenError, verifyIdToken } from "./google.ts";
import { signInAllowed } from "./ratelimit.ts";
import { mint, secretsEqual, SESSION_TTL_MS, verify } from "./session.ts";

export interface Env {
  DB: D1Database;
  GOOGLE_CLIENT_ID: string;
  GOOGLE_CLIENT_SECRET: string; // secret: needed to exchange a code for an ID token
  SESSION_SECRET: string;
  ADMIN_SECRET: string;
  SIGNIN_LIMIT?: RateLimit; // wrangler.toml [[ratelimits]]; absent in tests and bare `wrangler dev`
}

const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";

/** Exchange the browser's one-time code for an ID token. `redirect_uri` is
    literally "postmessage" for the GIS popup flow. Anything but a clean 200 is a
    401 - the code was wrong, reused, or for another client. */
async function exchangeCode(code: string, env: Env): Promise<string> {
  if (!env.GOOGLE_CLIENT_SECRET) throw new HttpError(503, "google-secret");
  let r: Response;
  try {
    r = await fetch(GOOGLE_TOKEN_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        code,
        client_id: env.GOOGLE_CLIENT_ID,
        client_secret: env.GOOGLE_CLIENT_SECRET,
        redirect_uri: "postmessage",
        grant_type: "authorization_code",
      }),
    });
  } catch {
    throw new HttpError(503, "google");
  }
  if (!r.ok) throw new HttpError(401, "token:code");
  const body = (await r.json()) as { id_token?: string };
  if (typeof body.id_token !== "string") throw new HttpError(401, "token:code");
  return body.id_token;
}

// Same allow-list as deploy/push-api/api/sub.js.
const ALLOWED_ORIGINS = new Set([
  "https://rosa.surf",
  "https://www.rosa.surf",
  "https://rosa-rust.vercel.app", // legacy origin, installed PWAs still live here
  "https://rosa-demo.vercel.app", // look-and-feel demo deploys
  "http://localhost:5173",
  "http://localhost:4173",
]);

const MAX_SPOTS = 200; // mirrors sub.js
const SPOT_ID = /^[\w-]{1,64}$/;
const MAX_BODY_BYTES = 4096;
const LAST_SEEN_THROTTLE_MS = 24 * 3600 * 1000;
const DAY_MS = 24 * 3600 * 1000;

interface UserRow {
  sub: string;
  email: string | null;
  name: string | null;
  picture: string | null;
  favorites: string;
  session_epoch: number;
  created_at: number;
  last_seen_at: number;
}

type Profile = Pick<UserRow, "sub" | "email" | "name" | "picture">;

function corsHeaders(req: Request): Record<string, string> {
  const origin = req.headers.get("Origin");
  if (!origin || !ALLOWED_ORIGINS.has(origin)) return {};
  return {
    "Access-Control-Allow-Origin": origin,
    Vary: "Origin",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Max-Age": "86400",
  };
}

function json(status: number, body: unknown, extra: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store", ...extra },
  });
}

class HttpError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function readJson(req: Request): Promise<Record<string, unknown>> {
  const len = Number(req.headers.get("Content-Length") ?? "0");
  if (len > MAX_BODY_BYTES) throw new HttpError(413, "body");
  const text = await req.text();
  if (text.length > MAX_BODY_BYTES) throw new HttpError(413, "body");
  try {
    const v: unknown = text ? JSON.parse(text) : {};
    if (typeof v !== "object" || v === null || Array.isArray(v)) throw new Error();
    return v as Record<string, unknown>;
  } catch {
    throw new HttpError(400, "json");
  }
}

function profileOf(row: UserRow): Profile {
  return { sub: row.sub, email: row.email, name: row.name, picture: row.picture };
}

function favoritesOf(row: UserRow): string[] {
  try {
    const v: unknown = JSON.parse(row.favorites);
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/** Validate a favorites list the way sub.js does, plus dedupe (order kept). */
function cleanFavorites(v: unknown): string[] {
  if (!Array.isArray(v) || v.length > MAX_SPOTS) throw new HttpError(400, "favorites");
  const out: string[] = [];
  for (const s of v) {
    if (typeof s !== "string" || !SPOT_ID.test(s)) throw new HttpError(400, "favorites");
    if (!out.includes(s)) out.push(s);
  }
  return out;
}

/** The signed-in user for this request, or a 401. Touches last_seen_at at most once a day. */
async function auth(req: Request, env: Env, ctx: ExecutionContext, now: number): Promise<UserRow> {
  const h = req.headers.get("Authorization") ?? "";
  const token = h.startsWith("Bearer ") ? h.slice(7).trim() : "";
  if (!token) throw new HttpError(401, "auth");
  const session = await verify(token, env.SESSION_SECRET, now);
  if (!session) throw new HttpError(401, "auth");
  const row = await env.DB.prepare("SELECT * FROM users WHERE sub = ?").bind(session.sub).first<UserRow>();
  if (!row || row.session_epoch !== session.ep) throw new HttpError(401, "auth");
  if (now - row.last_seen_at > LAST_SEEN_THROTTLE_MS) {
    ctx.waitUntil(env.DB.prepare("UPDATE users SET last_seen_at = ? WHERE sub = ?").bind(now, row.sub).run());
  }
  return row;
}

async function signIn(req: Request, env: Env, now: number): Promise<Response> {
  const body = await readJson(req);
  let credential: string;
  if (typeof body.code === "string" && body.code.length > 0 && body.code.length <= 512) {
    credential = await exchangeCode(body.code, env);
  } else if (typeof body.credential === "string" && body.credential.length > 0 && body.credential.length <= MAX_BODY_BYTES) {
    credential = body.credential;
  } else {
    throw new HttpError(400, "credential");
  }
  let claims;
  try {
    claims = await verifyIdToken(credential, env.GOOGLE_CLIENT_ID, { now });
  } catch (e) {
    if (e instanceof TokenError) throw new HttpError(401, `token:${e.message}`);
    throw new HttpError(503, "google"); // JWKS unreachable - try again, do not sign a stranger in
  }
  // Profile refresh on every sign-in, favorites untouched (the client merges its
  // pre-account list with a PUT right after).
  await env.DB.prepare(
    `INSERT INTO users (sub, email, name, picture, created_at, last_seen_at)
     VALUES (?1, ?2, ?3, ?4, ?5, ?5)
     ON CONFLICT(sub) DO UPDATE SET email = excluded.email, name = excluded.name,
       picture = excluded.picture, last_seen_at = excluded.last_seen_at`,
  )
    .bind(claims.sub, claims.email, claims.name, claims.picture, now)
    .run();
  const row = await env.DB.prepare("SELECT * FROM users WHERE sub = ?").bind(claims.sub).first<UserRow>();
  if (!row) throw new HttpError(500, "db");
  const token = await mint({ sub: row.sub, exp: now + SESSION_TTL_MS, ep: row.session_epoch }, env.SESSION_SECRET);
  return json(200, { token, profile: profileOf(row), favorites: favoritesOf(row) });
}

async function stats(req: Request, env: Env, now: number): Promise<Response> {
  const given = req.headers.get("x-admin-secret") ?? "";
  if (!env.ADMIN_SECRET || !(await secretsEqual(given, env.ADMIN_SECRET))) throw new HttpError(401, "auth");
  const row = await env.DB.prepare(
    `SELECT COUNT(*) AS users,
            SUM(created_at   > ?1) AS new_7d,
            SUM(created_at   > ?2) AS new_30d,
            SUM(last_seen_at > ?1) AS active_7d,
            SUM(last_seen_at > ?2) AS active_30d,
            SUM(json_array_length(favorites) > 0) AS users_with_favorites,
            COALESCE(SUM(json_array_length(favorites)), 0) AS favorites_total
     FROM users`,
  )
    .bind(now - 7 * DAY_MS, now - 30 * DAY_MS)
    .first<Record<string, number | null>>();
  const n = (k: string) => Number(row?.[k] ?? 0);
  return json(200, {
    users: n("users"),
    new_7d: n("new_7d"),
    new_30d: n("new_30d"),
    active_7d: n("active_7d"),
    active_30d: n("active_30d"),
    users_with_favorites: n("users_with_favorites"),
    favorites_total: n("favorites_total"),
    at: new Date(now).toISOString(),
  });
}

async function route(req: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const url = new URL(req.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  const now = Date.now();

  if (path === "/") return json(200, { ok: true, service: "rosa-user-api" });
  if (path === "/auth/google" && req.method === "POST") {
    if (!(await signInAllowed(req, env))) throw new HttpError(429, "rate");
    return signIn(req, env, now);
  }
  if (path === "/admin/stats" && req.method === "GET") return stats(req, env, now);

  if (path === "/me" && req.method === "GET") {
    const row = await auth(req, env, ctx, now);
    return json(200, { profile: profileOf(row), favorites: favoritesOf(row) });
  }
  if (path === "/me/favorites" && req.method === "PUT") {
    const row = await auth(req, env, ctx, now);
    const favorites = cleanFavorites((await readJson(req)).favorites);
    await env.DB.prepare("UPDATE users SET favorites = ?, favorites_updated_at = ? WHERE sub = ?")
      .bind(JSON.stringify(favorites), now, row.sub)
      .run();
    return json(200, { favorites });
  }
  if (path === "/auth/logout" && req.method === "POST") {
    const row = await auth(req, env, ctx, now);
    await env.DB.prepare("UPDATE users SET session_epoch = session_epoch + 1 WHERE sub = ?").bind(row.sub).run();
    return json(200, { ok: true });
  }
  if (path === "/me" && req.method === "DELETE") {
    const row = await auth(req, env, ctx, now);
    await env.DB.prepare("DELETE FROM users WHERE sub = ?").bind(row.sub).run();
    return json(200, { ok: true });
  }

  const known = ["/auth/google", "/auth/logout", "/me", "/me/favorites", "/admin/stats"];
  return json(known.includes(path) ? 405 : 404, { error: known.includes(path) ? "method" : "not found" });
}

export default {
  async fetch(req: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const cors = corsHeaders(req);
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    let res: Response;
    try {
      res = await route(req, env, ctx);
    } catch (e) {
      if (e instanceof HttpError) res = json(e.status, { error: e.message });
      else {
        console.error("user-api", e);
        res = json(500, { error: "internal" });
      }
    }
    for (const [k, v] of Object.entries(cors)) res.headers.set(k, v);
    return res;
  },
} satisfies ExportedHandler<Env>;
