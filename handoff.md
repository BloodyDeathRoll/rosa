# Session Handoff — 2026-10-12

## Goal
Non-code session: draft answers for the Claude startup program application ("what are you
building" and "where do you want support from Anthropic").

## Current State
- No code, data or infra changed. Working tree clean; HEAD = `761de35` (2026-10-11 Tango notice).
- Facts verified from the repo this session (2026-10-11):
  - First commit and Session 1: 2026-07-19.
  - Spot DB: 3056 spots in 127 region files (`data/spots/*.yaml`).
  - 681 commits in history, 638 with a `Co-Authored-By: Claude` trailer.
  - The Anthropic API is used only by `.github/workflows/claude.yml` and
    `claude-code-review.yml`. The forecast pipeline makes no Claude/LLM calls.
- Operator's final "what are you building" text (their wording, checked, not rewritten):
  > We've built Rosa.surf. Rosa is a free surf forecast app that covers over 3,000 spots
  > worldwide to date. It blends NOAA and ECMWF wave models, and uses physics each spot's
  > seafloor to predict waves. It checks accuracy against live buoys, updates four times a day
  > and publishes to a CDN. Claude reports it took us 681 commits so far.
  Only flagged issue: missing "and" in "uses physics each spot's seafloor".
- Operator's final "support" text: API credits + rate limits; add Claude to the forecast
  pipeline (skill-level fit per spot, best time of day, best tide per spot, plain-language
  reports); hitting Claude Code session limits often; early model access and guidance on
  running Claude at scale to keep the app free. Suggested tweaks: drop "Obviously",
  "the users" -> "our users". Whether the operator applied them or submitted: unknown.
- Carried over from the 2026-10-09 handoff, NOT re-checked this session: country chips live
  verification, Search Console tag, 4 held Normandy spots, SPOT-GAPS pins, iPhone sign-in
  test, official Open-Meteo 1.7.0+ switch, SWAN re-read due 2026-10-27.

## Active Files
- `handoff.md` - this file (overwrote the 2026-10-09 handoff; that one is in git at `aa4cf6c`).

## Changes Made This Session
1. Answered "when did we start Rosa" from git: 2026-07-19.
2. Drafted the application description; corrected Gemini's draft, which called Rosa
   "AI-powered" and said Claude parses the wave models. Both false: the forecast is physics,
   Claude built the code but does not run in the pipeline.
3. Corrected Gemini's support answer for the same reason (credits for "LLM-driven pipelines"
   claimed something not built). Reframed as planned future use of Claude in the pipeline.
4. Proposed future Claude-in-pipeline features (precomputed, static, fits "serve static"):
   skill fit, best time of day, best tide, plain-language reports, swell push text,
   trip planner, session log. Operator kept the first four.

## Failed Attempts
None.

## Next Step
1. Nothing pending from this session. If the operator raises Claude-in-pipeline features,
   they are ideas only - no plan, A/B or design exists; read `docs/rosa-build-plan.md` and
   `docs/OPEN-ITEMS.md` before proposing anything.
2. Re-open the 2026-10-09 next steps (`git show aa4cf6c:handoff.md`) and verify each against
   live state before acting; first is the country-chip check:
   `curl -s https://rosa-data-opal.vercel.app/data/index.json` -> `spots.atsunai.country == "Japan"`.
