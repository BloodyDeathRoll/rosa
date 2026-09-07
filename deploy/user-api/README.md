# rosa-user-api

Google sign-in and per-user favorites for Rosa. A Cloudflare Worker with a D1 (SQLite)
database. Lives at `https://rosa-user-api.einhanamer.workers.dev`. Nothing here touches
the forecast read path - that stays static on Vercel.

## Why this and not Supabase

The roadmap (`docs/rosa-accuracy-roadmap.md`) once named Supabase for the write plane.
Supabase bills per monthly active user (free to 50k, then $25/mo + $0.00325 per MAU past
100k, ~$3k/mo at 1M). Cloudflare bills per request: Workers Free is 100k requests/day and
D1 Free is 5M reads + 100k writes/day with 5 GB storage; the paid step is $5/mo for 10M
requests. At 1M users this is ~$5-15/mo. The user key is Google's `sub`, and the web app
talks only to the two calls below, so moving to any other host later is: export the
`users` table, run the same handler elsewhere, change `VITE_USER_API`.

## API

| Route | Auth | Body | Returns |
|---|---|---|---|
| `POST /auth/google` | none | `{code}` (one-time OAuth code from Google's account-chooser popup; `{credential}`, a GIS ID token, also accepted) | `{token, profile, favorites}` |
| `GET /me` | Bearer | | `{profile, favorites}` |
| `PUT /me/favorites` | Bearer | `{favorites: [spotId]}` (cap 200, `^[\w-]{1,64}$`, deduped) | `{favorites}` |
| `POST /auth/logout` | Bearer | | `{ok}` - revokes every session of that user |
| `DELETE /me` | Bearer | | `{ok}` - the row and everything in it |
| `GET /admin/stats` | `x-admin-secret` | | user counts (below) |

The browser uses the GIS **code client** (`google.accounts.oauth2.initCodeClient`, popup,
`select_account: true`) so a surfer with two Google accounts always gets the chooser; the
Worker exchanges the code at `oauth2.googleapis.com/token` with `GOOGLE_CLIENT_SECRET`
(`redirect_uri=postmessage`) and verifies the returned ID token like any other.

Sessions are stateless HMAC tokens (`src/session.ts`, 180 days) carrying the user's
`session_epoch`; a logout bumps the epoch and every token dies. Google credentials are
verified against Google's JWKS in `src/google.ts` (RS256, `iss`, `aud` = our client id,
`exp`, `email_verified`). CORS is an explicit origin list (same as `deploy/push-api`).

## Schema

`schema.sql` - one `users` row per Google account, favorites as a JSON column (one row
write per toggle), `last_seen_at` written at most once a day.

## One-time setup (done 2026-09-07, kept for a rebuild)

```sh
cd deploy/user-api
npm install
npx wrangler login                                   # browser approval
npx wrangler d1 create rosa-users                    # paste database_id into wrangler.toml
npx wrangler d1 execute rosa-users --remote --file schema.sql
grep '^GOOGLE_CLIENT_SECRET=' ../../.env.local | cut -d= -f2- | npx wrangler secret put GOOGLE_CLIENT_SECRET   # the repo-root .env.local holds it (gitignored)
openssl rand -hex 32 | npx wrangler secret put SESSION_SECRET
openssl rand -hex 32 | tee ~/rosa-push/user-api-admin-secret.txt | npx wrangler secret put ADMIN_SECRET
npx wrangler deploy
```

`GOOGLE_CLIENT_ID` is a plain var in `wrangler.toml` (it is public; the web app ships
the same value as `VITE_GOOGLE_CLIENT_ID`). The OAuth client lives in the Google Cloud
project "Rosa" (Google Auth Platform > Clients > `rosa-web`), authorized JS origins =
the six origins in `src/index.ts` `ALLOWED_ORIGINS` plus `http://localhost`.

Rotating `SESSION_SECRET` signs everyone out. Never rotate it casually.

## Deploy

```sh
cd deploy/user-api && npm test && npx wrangler deploy
```

## Local development

```sh
cd deploy/user-api
printf 'SESSION_SECRET=dev-secret-%s\nADMIN_SECRET=dev-admin\nGOOGLE_CLIENT_SECRET=<same value as the repo-root .env.local>\n' "$(openssl rand -hex 16)" > .dev.vars
npm run db:local          # schema into the local D1
npm run dev               # http://localhost:8787
```

The web app's `.env.development` points `VITE_USER_API` at `http://localhost:8787`.
Google's button only works on `http://localhost:5173`, not `127.0.0.1` or a LAN IP.

Smoke without a Google account: insert a row and mint a session for it.

```sh
npx wrangler d1 execute rosa-users --local --command \
  "INSERT INTO users (sub,email,name,created_at,last_seen_at) VALUES ('u1','a@b.c','A',0,0)"
TOK=$(node -e 'import("./src/session.ts").then(async m=>console.log(await m.mint({sub:"u1",exp:Date.now()+864e5,ep:0},"<SESSION_SECRET from .dev.vars>")))')
curl -H "Authorization: Bearer $TOK" http://localhost:8787/me
curl -X PUT -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"favorites":["poleg"]}' http://localhost:8787/me/favorites
```

## Existing users' favorites (the pre-account import)

Nothing to run. Before 2026-09-07 favorites lived only in the browser's
`localStorage["rosa.favorites"]`; the updated app keeps reading that key. On a user's
FIRST sign-in the app merges it into the account (server list first, then any local
spot the account did not have) with one `PUT /me/favorites`, and from then on the
account is the truth on every device. A second device with a different old list
merges the same way when it signs in. Nothing is imported for a user who never
signs in - they keep seeing their local list, they just cannot change it.

## How many users

```sh
curl -s -H "x-admin-secret: $(cat ~/rosa-push/user-api-admin-secret.txt)" \
  https://rosa-user-api.einhanamer.workers.dev/admin/stats
```

```json
{"users":1,"new_7d":1,"new_30d":1,"active_7d":1,"active_30d":1,
 "users_with_favorites":1,"favorites_total":2,"at":"2026-09-07T17:00:00.000Z"}
```

`users` is everyone who ever signed in. `active_*` counts users seen in the window
(`last_seen_at`, touched at most once a day per user). Vercel Web Analytics still counts
anonymous visitors; the two together are "visitors" and "accounts". The Cloudflare
dashboard (Storage & Databases > D1 > rosa-users) shows the row count as a cross-check.

## Tests

`npm test` - `node --test`, no dependencies: the Google verifier (good token; expired,
wrong audience, wrong issuer, unverified email, unknown kid, forged signature, tampered
payload, `alg=none`) and the session HMAC (round-trip, expiry, tamper, wrong secret).

## Limits and the first ceiling

Workers Free: 100k requests/day. D1 Free: 100k row writes/day, 5M reads/day, 5 GB.
A toggle is one write; a launch is one read. The first thing to hit is writes at
~100k toggles/day; the fix is the Workers Paid plan ($5/mo), not a redesign.
