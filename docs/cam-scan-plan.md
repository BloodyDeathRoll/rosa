# Cam-scan: finding live surf webcams on YouTube

Method devised 2026-07-27 after the first manual sweep (5 cams added that day).
Tool: `tools/cam-scan/scan.py`. Only **officially embeddable YouTube live
streams** ever qualify - proprietary cam players (beachcam.co.il, lankasurf,
MEO Beachcam, popoyo.com...) are legally off-limits (CLAUDE.md red lines);
those need partnerships instead.

What the manual sweep taught us, baked into the design:
- **Networks beat searches**: one channel (The Surfers View, Playocean,
  ii-nami.com...) carries many cams. Channel mining is the highest-yield query.
- **Local language finds what English can't**: the Japanese cams surface only
  for ライブカメラ / 波情報; Hebrew cams for מצלמה; Portuguese for livecam praia.
- **Cam titles and pins can disagree** (the Hagolshim lesson) - matching is a
  proposal, the reviewed git diff is the gate.

## 1. Discovery - YouTube Data API v3, not scraping

`search.list` with `type=video&eventType=live`. HTML/ytInitialData parsing is
fine for a one-off but fragile and ToS-gray as automation; the API is free.
Quota 10,000 units/day; every search costs 100 → ~90 searches/day, so sweeps
are budget-tracked and resumable (`data/cams/seen.json` remembers query dates
and verdicts across runs).

Setup (one-time): enable "YouTube Data API v3" on the Google Cloud project,
put the key in `YOUTUBE_API_KEY` (VM: `~/.rosa-env`).

Two modes, cheapest first:
1. **Channel mining** (`scan.py channels`): enumerate every current live
   stream of the channels in `tools/cam-scan/channels.yaml`. Every accepted
   cam's channel joins the seed list.
2. **Query sweep** (`scan.py sweep`): generated queries - per spot and per
   region - from language-aware templates (`TEMPLATES` in scan.py).

## 2. Filtering - cheap API checks

One batched `videos.list` (1 unit / 50 videos) per candidate set gives:
- `status.embeddable` - the legal gate (same check oEmbed gave us manually)
- `snippet.liveBroadcastContent == "live"`
- `liveStreamingDetails.actualStartTime` age ≥ 12 h - a stream live for days
  is a 24/7 cam; live for 40 minutes is someone filming their session

## 3. Matching cams to spots

- Candidate found by a spot query, or a spot name in the title → proposed for
  that spot (plus distance sanity via `--geocode`, Google legacy textsearch -
  the same provider as tools/spot-verify).
- No spot nearby → `unmatched` list = **spot-discovery signal** for the
  worldwide scale-up (someone pointed a camera at that break).
- Output is `data/cams/candidates.yaml` - reviewed by eye, then applied to the
  spot YAMLs as a normal committable diff. No interactive gates.

## 4. Keeping cams alive - `scan.py verify`

24/7 streams **rotate video IDs** on restart, so a static `cam.yt` silently
dies. Weekly: one batched `videos.list` over every assigned cam reports
dead/unembeddable ones; `--resolve` finds the channel's current live stream
(100 units/cam) and `--apply` patches the spot YAML in place. Wire into the VM
cron once the API key lives there (stage 2).

## 5. Rollout

1. DONE here: the tool + seed channels; first sweep over the 7 regions.
2. `verify` on the VM cron (weekly), API key on the VM.
3. Worldwide: same machinery over a coastline/language region list instead of
   the spot DB; `unmatched` output feeds the spot-DB expansion.
