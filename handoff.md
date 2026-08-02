# Session Handoff - 2026-08-02 (evening, short session)

## Goal
User reported two live faults from his phone at 20:37 Israel time: the Santa Teresa YouTube cam
showed "Video unavailable", and the forecast was "still way too low" against a Surfline
side-by-side. Diagnose both and get the fix in front of him.

## Current State
- **No code was written this session.** Nothing committed, tree clean, main still at `8f65333`.
  Both reported faults were already fixed in the repo by session 12; neither had reached the user.
- **Root cause for both: rosa-data had not been republished since session 12's push.** The app was
  serving the 14:20 UTC cycle (`fetched_at 2026-08-02T14:36:33Z`), which ran ~3 h before the push.
- **A publish cycle was triggered manually at 17:45:21Z and COMPLETED CLEAN at 18:51:21Z**
  (`=== 2026-08-02T18:51:21Z done ===`, no `FAILED at:`, **no `warn:` and no 429 anywhere in the
  cycle** - so gwam at `MARINE_BATCH_SIZE = 65` is now proven on the cron path). It pulled the VM
  checkout from session 11's `3be95b3` to `8f65333`, making it the first cycle to carry the K&G
  closure, `RIDEABILITY_EXP` 2.2, gwam Tp, batch 65 and the 183 new swell windows.
- **Session 12's work is LIVE.** Served payload: `fetched_at 2026-08-02T18:02:25Z`,
  cam `Pm-Bh1r7YuM`, `peak_period 11.2` on the leading partition. All three pre-fix markers flipped.
- **Santa Teresa now reads 0.9-1.7 m, "head-high", FIRING/GOOD** across today (h_mid 1.1-1.5).
  Note this is **above** session 12's stated 0.9-1.5 and well above Surfline's flat 0.6-1.1 m.
  The user's eye said ">1 m", so it is not contradicted - but the top of the range is the least
  supported part, exactly as session 12 warned. **Not yet seen by the user.**

## Active Files
None modified. Files only read: `deploy/oracle/publish.sh`, `web/src/api.ts`,
`web/.env.production`, `data/spots/costa-rica.yaml`.

## Changes Made This Session
1. **Diagnosis, cam.** Verified against YouTube's watch-page `playabilityStatus`, not oEmbed:
   old id `SuVmuBKsURo` is `UNPLAYABLE` / "This live stream recording is not available", with
   `liveBroadcastDetails.endTimestamp 2026-07-30T15:52:34Z`. New id `Pm-Bh1r7YuM` is `status: OK`,
   `isLiveNow: true`, `startTimestamp 2026-07-30T15:56:26Z`. The 4-minute gap confirms the
   id-rotation reading from session 12. The repo already had the new id; the **served** payload
   still carried `SuVmuBKsURo`.
2. **Diagnosis, height.** Three independent markers in the served payload proved it was pre-fix
   data, not a bad fix: `peak_period: null` on every partition (no gwam), the 03:00 partition at
   187 deg flagged `in_window: false` (that is the old `[190,310]` window; the new `[160,290]`
   contains it), and the old cam id. Screenshot numbers (0.5-0.9 m) matched the served hours
   exactly.
3. **One new observation worth keeping.** Surfline's primary at Santa Teresa today is **0.7 m
   @ 12 s @ 215 deg**; Open-Meteo's largest partition in the same hours is 0.84 m @ 8.8 s @ 190 deg
   with no Tp at all. So at this spot the missing gwam Tp was not a small display matter - with
   `peak_period` null, `period_rideability` keyed on the 8.8 s **mean** and at exp 2.2 that
   attenuates hard. The gwam fix and the closure both push the same direction here.
4. **Triggered `publish.sh` manually** rather than waiting for the 20:20 UTC cron (2 h 36 min away
   at the time; a cycle takes 60-90 min, so no collision risk). Checked the VM was idle first
   (last cycle `done` at 15:23:07Z, no `publish.sh`/`rosa-pipeline` processes).

## Failed Attempts
- **`curl .../spots/santa-teresa.json` 404s.** The rosa-data project serves under **`/data/`** -
  the correct URL is `https://rosa-data-opal.vercel.app/data/spots/<id>.json` (see `web/src/api.ts`).
- **YouTube oEmbed cannot tell a live stream from a dead one.** Both the dead and the live id
  returned HTTP 200 with an identical title from `/oembed`. Same for `GET /embed/<id>`, which
  returns ~135 KB of HTML with no `playabilityStatus` in it. **Only the watch page carries
  `"status":"UNPLAYABLE"` / `liveBroadcastDetails`** - that is the check to use, and it is what any
  future cam-liveness tooling should key on. (Session 12's rule still stands on top of it: diff the
  TITLE before adopting a replacement, and never let `verify --resolve --apply` run unattended.)
- Nothing else failed. No code was changed, so nothing regressed.

## Next Step
1. **Ask the user to re-check Santa Teresa** (nothing to run first - it is live). Expect
   **0.9-1.7 m, head-high** and a playing cam. This is the real test of session 12's x1.39: his eye
   said ">1 m", Surfline says a flat 0.6-1.1 m, and Rosa now reads above both. **If he says it now
   reads too HIGH, that is the first evidence against the closure** - log it in CALIBRATION.md as a
   graded frame, do not reach for a knob on one report.
2. **Verification commands, if the state needs re-checking:**
   ```
   ssh -i web/.oracle/ssh-key-2026-07-23.key ubuntu@82.70.218.149 \
     'grep -nE "^=== |FAILED at:|warn:" ~/rosa/publish.log | tail -8'
   curl -s https://rosa-data-opal.vercel.app/data/spots/santa-teresa.json | python3 -c \
     "import sys,json;d=json.load(sys.stdin);print(d['fetched_at'],d['spot']['cam']['yt'],d['hours'][0]['swells'][0].get('peak_period'))"
   ```
   Payload hour keys are `t`/`h`/`h_mid`/`phrase` (not `time`/`h_break_m`).
3. **The 20:20 UTC cron fired ~1.5 h after the manual cycle and its result was never checked** -
   it should be a clean no-op republish. `publish.sh` has no lock, but the two never overlapped.
4. Unchanged from session 12's handoff: more eye frames in a long-period region; the 16 held swell
   windows want eyes (`calicoan-abcd`, `zavial`, `kodomonokuni`, 10 NARROW-flagged,
   `pavones`/`panga-drops`/`miura`, plus `playa-cocles` which still excludes its own shore normal);
   `horizon` is blind below ~450 m so a derived window is an upper bound on exposure; the de-bias
   plan stays retired; do not scale partitions to close `closure`; no partition temporal smoothing;
   the ~+16 deg `mwd` bias needs a per-partition measurement first; "should a blown-out sea read
   smaller?" is still an unmade product call; and whether `period_score` and the shoaling march
   should follow rideability onto Tp is its own experiment.
