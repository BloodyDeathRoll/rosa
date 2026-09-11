# Security

## Reporting

Open a private vulnerability report on this repository (GitHub > Security > Report a
vulnerability), or use Contact in the app and say it is a security issue. Please do not
open a public issue.

## What is public on purpose

- `web/.env.production` - every `VITE_*` value is inlined into the shipped JavaScript: the
  data, push and user-api origins, the Google OAuth client id, the GA id, and the **public**
  half of the VAPID key pair. A secret must never go in a `VITE_*` variable.
- The forecast data (`rosa-data`), the spot database (`data/spots/`) and the rating formula.

## Secrets: where they live, what rotating costs

One maintainer holds all of them. None is in git.

| Secret | Lives in | Rotating it |
|---|---|---|
| `VERCEL_TOKEN` | box `~/rosa/.env`; workstation `.env.local` | Vercel > Account > Tokens; update both files. The next cycle fails until the box has it. |
| VAPID private key | box `~/rosa-push/vapid_private.pem` (`VAPID_PRIVATE_KEY`); backup `~/.config/rosa/private_key.pem` | **Invalidates every push subscription on every device.** Only if leaked. The public half is `VITE_VAPID_PUBLIC`. |
| `PUSH_ADMIN_SECRET` | `rosa-push` Vercel env; box `~/rosa/.env`; backup `~/.config/rosa/push-admin-secret.txt` | Set the new value in all three, then redeploy `deploy/push-api`. Until the box has it, alerts and feedback pulls get 401. |
| `SESSION_SECRET` | `rosa-user-api` Worker secret | `npx wrangler secret put SESSION_SECRET`. **Signs every user out.** |
| `ADMIN_SECRET` (user-api) | Worker secret; workstation `~/rosa-push/user-api-admin-secret.txt` | `wrangler secret put ADMIN_SECRET`, update the file `stats.sh` reads. |
| `GOOGLE_CLIENT_SECRET` | Worker secret; workstation `.env.local` | Google Cloud "Rosa" > Clients > `rosa-web`, then `wrangler secret put`. Sign-in fails until both match. |
| `GOOGLE_MAPS_API_KEY` (also the YouTube Data API) | box `~/rosa/.env`; workstation `.env.local` | Google Cloud console; update both. Cam checks and spot tooling stop until then. |
| `HEALTHCHECK_URL` | box `~/rosa/.env` | healthchecks.io. It is a capability: whoever holds it can silence the outage alert. |
| `COPERNICUS_USER` / `COPERNICUS_PASS` | workstation `.env.local` | Copernicus Marine account; hand-run `sdb` tooling only. |
| VM SSH key | workstation `~/.config/rosa/ssh-key-2026-07-23.key` | New key pair into the box's `~/.ssh/authorized_keys`. The backup is reached through the box with the box's own key, so it is untouched. |
| GA reporting key | workstation `~/.config/rosa/ga-sa.json` | Google Cloud service account; `tools/ga-report` only. |
| Box deploy key | box `~/.ssh/rosa_deploy` | Read-only on GitHub (Settings > Deploy keys) - it can pull, never push. |

Workstation secrets sit in `~/.config/rosa/` (mode 700), outside the repo directory, so a
session working in the repo does not hold the box's key (audit 2026-09-11).

## Controls in place

- **Static site headers** (`web/vercel-output.json`): `nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy`, `Permissions-Policy`.
- **Push endpoints**: `deploy/push-api/api/sub.js` accepts only the browsers' push services,
  and the box's sender (`notify.is_push_endpoint`) re-checks every stored endpoint before it
  POSTs.
- **Admin surfaces** compare `x-admin-secret` in constant time (push-api `api/_admin.js`,
  user-api `secretsEqual`).
- **Sign-in** is rate-limited per IP in the Worker; Google ID tokens are verified against
  Google's keys (`iss`, `aud`, `exp`, `email_verified`); sessions are HMAC with an epoch
  that a logout bumps.
- **Dependencies**: Dependabot with a 7-day cooldown; `.github/workflows/checks.yml` runs
  the tests, ruff, `tsc` and the builds on every PR.
- Security audits live outside the repo: `~/Projects/swarm/audits/rosa/`.
