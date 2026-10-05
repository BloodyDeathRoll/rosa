-- Rosa users: one row per Google account. Favorites live in a JSON column so a
-- toggle is exactly ONE row write (D1 bills rows written; a rows table would be
-- DELETE-all + INSERT-N per save) and the list keeps the order the Spots tab
-- renders in. Times are unix milliseconds.
--
-- Apply: `npx wrangler d1 execute rosa-users --remote --file schema.sql`
-- (idempotent - IF NOT EXISTS everywhere).
CREATE TABLE IF NOT EXISTS users (
  sub TEXT PRIMARY KEY,                       -- Google's stable user id (vendor-neutral key)
  email TEXT,
  name TEXT,
  picture TEXT,
  favorites TEXT NOT NULL DEFAULT '[]',       -- JSON array of spot ids, order preserved
  favorites_updated_at INTEGER,
  session_epoch INTEGER NOT NULL DEFAULT 0,   -- bump = every session token for this user dies
  created_at INTEGER NOT NULL,
  last_seen_at INTEGER NOT NULL               -- written at most once per 24 h per user
);
CREATE INDEX IF NOT EXISTS users_created ON users(created_at);
CREATE INDEX IF NOT EXISTS users_last_seen ON users(last_seen_at);

-- TEMPORARY (2026-10-06): which Android app opens rosa.surf/?token=…&accountId=…
-- (web/src/probe.ts). One row per such load, no IP, capped at 5000 rows by the Worker.
-- Drop the table with the route once the app is named.
CREATE TABLE IF NOT EXISTS probes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at INTEGER NOT NULL,                        -- unix ms
  country TEXT,                               -- Cloudflare's request.cf.country
  asn INTEGER,                                -- the network: a datacenter here means a bot farm
  as_org TEXT,
  headers TEXT NOT NULL,                      -- JSON, IP/cookie/auth headers removed
  client TEXT NOT NULL                        -- JSON the page sent (probe.ts)
);
