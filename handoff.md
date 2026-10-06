# Session Handoff — 2026-10-06

## Goal
Explain the Arab-country traffic in Rosa's analytics, find which Android app opens
`rosa.surf/?token=…&accountId=…&username=…&webview=ANDROID_WEBVIEW`, and name it.

## Current State
- Explained in part: since 2026-09-03 an unknown Android app opens rosa.surf's home page
  with its own one-minute sign-in token (EdDSA JWT, `iss: token-service`, `aud: autologin`,
  `flow: DEFAULT`, one `kid`). GA4 (28 d to 10-05): ~950 such loads from ~690 of its
  accounts; ~480 of ~1000 Rosa users were in Arab countries, all "direct", home page only,
  ~40 s, one spot_view per ~8 users. The app is still unnamed.
- Visitors are real phones (20 models, Arabic/Turkish/Persian/Spanish/Russian locales) in
  the phone's own Chrome / Samsung browser, no referrer, no injected globals - the link is
  handed to the system browser (or Custom Tabs). Some arrive via VPN/datacenter exits.
- rosa.surf has no prior owner: first certificates ever are 2026-09-06 (the cutover day).
- Rosa VPN (`com.roza.vpn`, 5M+ installs, same regions) was the best suspect; its public
  package and site reference neither rosa.surf nor this URL shape. Not proven, not excluded.
- LIVE, TEMPORARY instrumentation (both deployed and verified end to end):
  1. `POST /probe` on the user API + D1 table `probes` (Worker version 9bcc3440). The page
     posts UA, client hints, referrer, query keys, globals on exactly those loads. 23 rows
     by 10-06 09:57 local; they are what the "real phones" statement above rests on.
  2. A card "Which app brought you here?" (7 languages, text box, Send) shown ONLY on those
     loads, above the sign-in screen. Live on rosa.surf since 10-06 ~10:30 local
     (`index-8NxDzNk9.js`). Zero answers read yet.
- Privacy page has a paragraph on this recording. Not yet in `docs/UI.md`.
- The other 10-06 session (Dream review) committed `e549205` (swellmap parse guard) and
  `1441feb` (stage-4 SWAN); see `docs/SESSIONS.md` 2026-10-06 entries. VM pull of those
  is unverified.
- Separately noticed: first-time visitors land on the full-screen "Continue with Google"
  sign-in. Not changed; reported only.

## Active Files
- `web/src/probe.ts` - detects the foreign-app load, posts the browser's self-description, sends the answer.
- `web/src/components/ForeignAppAsk.tsx` - the "which app?" card; `app.tsx` mounts it after `ConsentBar`.
- `web/src/styles.css` - `.ask-app*` rules (z-index 9999, above `.signin-screen` 9998).
- `web/src/main.tsx` - calls `probeForeignApp()` at boot, before the router touches the URL.
- `web/src/pages/AboutPage.tsx` - privacy paragraph.
- `deploy/user-api/src/index.ts` - `probe()` route, `PROBE_DROP` headers, 5000-row cap; `wrangler.toml` `PROBE_LIMIT` 10/min/IP; `schema.sql` `probes` table.
- `tools/ga-report/report.py` - reused (unchanged) for the ad-hoc GA4 queries.

## Changes Made This Session
1. GA4 read by country, source, browser, language, events, token URLs (script in scratchpad, not committed). Decoded every token: one `kid`, 693 accountIds, iat = open time.
2. `bd86a54` probe: Worker route + D1 table + page call. No IP, token, accountId or username stored - the question is which app, not which person. Deployed; test row inserted, read back, deleted.
3. Domain history (certspotter), Rosa VPN listing/site/public package checked, GitHub code search for the URL shape (nothing).
4. `d0a5a5e` the ask card, gated on `webview=ANDROID_WEBVIEW` or `token`+`accountId`. Screenshot-verified in ar/tr and absent without params. Deployed.
5. Memory `token-app-probe-read-due-2026-10-07`: remind at the 10-07 dream review.

## Failed Attempts
- Vercel Web Analytics API: "Web Analytics not found" on project `rosa`; Hobby runtime logs keep 1 h and the `token=` query timed out. Not a source.
- Web/GitHub searches for the JWT `kid`, `webview=ANDROID_WEBVIEW`, `aud autologin token-service`: nothing.
- Wayback (429), rdap.org (403), crt.sh (502) all unreachable from here; certspotter answered instead.
- `npx wrangler` in the worktree deployed to the wrong account twice: the Worker lives in
  einhanamer@gmail.com (`c283cc56…`), and `node_modules/.cache/wrangler/wrangler-account.json`
  cached the outlook account. Fix: `CLOUDFLARE_ACCOUNT_ID=c283cc56c3871e4f4683b478e5c1da24` and delete that cache file.
- `.githooks/pre-push` needs `uv` on PATH (`PATH=$HOME/.local/bin:$PATH`).
- `pkill -f "vite preview"` killed the calling shell (exit 144) - match the pid, not the string.
- Playwright is not installed in `web/`; the screenshot script ran from `~/Projects/oneshot-old-2026-10-02`.

## Next Step
On/after 2026-10-07 read the answers:
`cd deploy/user-api && CLOUDFLARE_ACCOUNT_ID=c283cc56c3871e4f4683b478e5c1da24 npx wrangler d1 execute rosa-users --remote --json --command "SELECT at, country, json_extract(client,'\$.answer') a, json_extract(client,'\$.lang') l FROM probes WHERE json_extract(client,'\$.kind')='answer'"`
Then:
- If the app is named: remove `probe.ts`, `ForeignAppAsk.tsx`, the `/probe` route, `PROBE_LIMIT`,
  the `probes` table and the privacy paragraph; log the answer in `docs/SESSIONS.md`.
- If no answers after a few days: email Rosa VPN support (rosaconnect.online) asking whether their app links to rosa.surf; the operator had agreed to this on 10-06 but it was not sent.
- Add the probe/ask card to `docs/UI.md` while it lives.

---

## Parallel session 2026-10-06: showreel (marketing video, no repo code)
- The operator picked **v14 blues** on 2026-10-06. There are 4 renders in `~/Videos/rosa-showreel-v14-30s-blues{,-light,-9x16,-light-9x16}.mp4`. I checked them as stills only; I never heard the audio.
- What changed from v7:
  - The phone floats in 3D the whole time.
  - "Your favorites" is callout A in the same CLEAR wave as the other three.
  - The GETS BETTER globe and graph are centered.
  - The ending zooms into the spinning globe, then the wave footage fades in.
  - "Showreel" is gone from the top-right corner.
  - Light versions: the CTA and tag text are white on color, and the black logo keeps a blue icon and dot (memory `rosa-showreel-light-rules`).
- The operator's sound rules: no bells; a swoosh only on the 5 step-title cards; the beat plays straight under the titles. The music is "Old Steel (Blues Rock Promo)" by AlexGrohl (Pixabay, free licence).
- **The sources exist only in a scratchpad, which gets wiped:** `/tmp/claude-1000/-home-shahar--superset-worktrees-rosa-fluff-spacecraft-fbe83e80/09b632a0-5b96-48b7-bb88-e0e2e1099dfb/scratchpad/re/fable/`
  - The film is `reel13.html` (switches `?theme=light`, `?ar=916`). It was built by the patch chain `mk8.py`..`mk13.py`.
  - The soundtrack: `python3 audiov15.py blues` (chain `mka10`..`mka15`).
  - Render with `Q=... OUT=frq WK=20 node render13.cjs`, then `ffmpeg tmix=frames=4,fps=60`.
  - Next step: ask the operator where to keep them. The v7 sources were lost once already and had to be rebuilt by replaying the session JSONL.
- The numbers on screen (2,741 spots, 0.74/1.04 s on 4G, 78 KB, 620 updates) were true on 2026-10-04. The app screens are from live rosa.surf on 2026-10-05.
