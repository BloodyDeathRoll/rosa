# Session Handoff — 2026-09-12 (afternoon, SEO)

## Goal
Make rosa.surf indexable now that it draws organic traffic: real paths instead of hash
routes, per-page head, prerendered shells, sitemap. Plus two UI asks (hour labels full
black; Best-session pill in the Epic dark green).

## Current State
All of it is merged to `main` (PR #20, merge `c252fd6`) and **deployed to production**
2026-09-12 ~14:20 UTC. Verified live: `/sitemap.xml` 200 with 1,955 URLs, `/robots.txt`
200, `/spot/pipeline` 200 with its own title, `/about/how` 200, `/spot/does-not-exist`
404. Lighthouse 13.4.1 SEO 100 on `/`, a spot page and an About page (preview build).
Headless Chrome check passed: path routes render, `/#/spot/x?ev=..` becomes
`/spot/x?ev=..`, in-app links do not reload, back works, titles and JSON-LD follow the
route, `/#/spots?import=a,b` imports favorites, one JSON-LD block per page after render.

Untested: an installed PWA on a real phone after this deploy (SW `navigateFallback`
serves the shell for `/spot/x`; expected fine, not observed). Google Search Console has
NOT been given the sitemap yet - the user has the domain verified and was handed the URL.

Only `handoff.md` is uncommitted.

## Active Files
- `web/src/router.ts` (new) - parseRoute/pathFor/navigate/onRouteChange/adoptLegacyHash/interceptLinks.
- `web/src/head.ts` (new) - setHead (title, description, canonical, OG, robots, JSON-LD in `#ld-page`), spotHead.
- `web/src/seo.ts` (new) - headFor(route); spot case is a no-op (SpotPage owns its head).
- `web/src/app.tsx` - route from `currentPath()`, headFor on route change, interceptLinks.
- `web/src/main.tsx` - adoptLegacyHash() before render; `?import=` read from the query; `#app` emptied before render (Preact 10 `render` does NOT remove pre-existing root children - verified).
- `web/src/analytics.ts`, `ga.ts`, `contact.ts` - paths not hashes; pageviews on the router event.
- `web/src/pages/SpotPage.tsx` - `?ev=` from `location.search`, reacts via onRouteChange; setHead from index entry then payload (full published name).
- All pages/components with links: `href="#/x"` -> `href="/x"`, `location.hash =` -> `navigate()`.
- `web/scripts/prerender.mjs` (new) - after `vite build`: 1947 `dist/spot/{id}.html` (index fetched from `VITE_DATA_BASE`, `public/data` fallback), `dist/about/*.html` via `preact-render-to-string` (contact excluded - its form reads the browser at render), one shell per other screen, `sitemap.xml`. Refuses to run if `dist/spot` exists or `dist/sw.js` is missing.
- `web/src/prerender-entry.tsx` (new) - `vite build --ssr` entry exporting renderAbout.
- `web/index.html` - new head (canonical, OG 1200x630, twitter large image, WebSite JSON-LD with `id="ld-page"`), static crawler block inside `#app`.
- `web/public/robots.txt`, `web/public/og.jpg` (new).
- `web/vercel-output.json` - `handle: filesystem` -> `/spot/x` to `/spot/x.html` (`check: true`) -> about/screens -> aliases -> `/index.html` with status 404.
- `web/vite.config.ts` - `navigateFallbackDenylist` for `/data/` and `.xml|.txt|.json`.
- `web/package.json` - `build` runs `prerender`; devDependency `preact-render-to-string@6.7.0`.
- `web/src/styles.css` - `.hour-grid .t` black (`--foreground` dark); `.best-tag` background `--rating-firing`.
- `docs/UI.md` (Routing and SEO paragraph), `docs/OPEN-ITEMS.md` 35, `docs/SESSIONS.md`, `.gitignore` (`web/dist-ssr/`).

## Changes Made This Session
1. Hour column full black - user ask.
2. SEO tool research (subagent, web): no official Anthropic/Google/Vercel SEO plugin. Meets the bar: Lighthouse CLI, chrome-devtools-mcp, Unlighthouse, vendor-hosted DataForSEO/Ahrefs/Semrush MCPs. Rejected solo-maintainer Search Console MCPs, archived Ahrefs local server. Memory `seo-tools-shortlist`.
3. Hash -> path routing with legacy adoption (the one real SEO problem: one crawlable URL for 1,947 spots).
4. Per-page head + prerendered shells + sitemap + robots + OG image; Vercel routes with real 404s.
5. Best-session pill -> Epic green (`3e682dd`).
6. Review round: GitHub mention review found the JSON-LD duplication (static block lacked `id="ld-page"`, setHead appended a second) - fixed `aa63380`. Also: SpotPage alone owns the spot head (`7926b97`), prerender ordering guard, stale comment.
7. Merged with a merge commit (user: "review and merge"), then `npm run deploy` from `web/`.

## Failed Attempts
- **`/code-review 20 high` twice**: seven subagents each re-reading the 36-file diff; first run died on the session rate limit, I relaunched it, then killed it. Burned ~60% of the user's session budget for one finding the GitHub review also raised. User was angry. Memory `no-heavy-local-audits` written: never fan-out audits in-session, never relaunch after a quota kill; GitHub review + one hand read is the audit.
- The `claude-code-review.yml` workflow (plugin `/code-review --comment`) passes with **no visible output** and 1-28 permission denials per run (only the inline-comment tool is allowed). It cannot be treated as evidence of a review. The `@claude review` mention (`claude.yml`) does post a real review - use that.
- First `@claude review` mention died after 1 min on the same rate limit (shared OAuth token); re-mention after reset worked.
- SSR of the Contact page: `contact.ts` reads `location` at render -> excluded from prerender.
- `pkill -f "vite preview"` killed the calling shell too (exit 144) and silently skipped a python edit in the same command; the edit was redone later.
- Playwright's bundled chromium was missing; used `executablePath: /usr/bin/google-chrome` with the `uptake` project's playwright module.

## Next Step
1. Submit `https://rosa.surf/sitemap.xml` in Google Search Console (domain already verified per the user) and request indexing of `/`, `/map`, `/about/how`, `/about/reading`.
2. OPEN-ITEMS 35: `notify.py` still emits `/#/spot/{id}?ev=` (works via adoptLegacyHash; change with `test_notify.py`); per-spot OG card; drop the stale `web/public/data` copy from the build; **new spots need `cd web && npm run deploy`** before `/spot/{id}` returns 200 (or move the prerender into `publish.sh`).
3. Reported, not changed: Lighthouse performance 75-88 - the 1 s splash and the autoplay cam give CLS 0.32 on spot pages; `public/splash_16-9.png` is 3.8 MB.
4. Consider giving `claude-code-review.yml` a comment tool (or dropping it) since it posts nothing.
