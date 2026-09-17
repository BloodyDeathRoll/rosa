# Rosa progress

Last updated: 17 Sep 2026. Updated at every `/session-off` (project skill `.claude/skills/session-off`).

## Status now
- **Live and healthy.** 2,254 spots worldwide, a 15-day forecast, updated 4 times a day. Last update checked: 01:32 on 17 Sep.
- **South America is in (16 Sep):** Chile, Ecuador, Uruguay, Argentina and the three missing Brazilian states - 307 new spots, every pin checked on satellite photos.
- **Wave data** comes from NOAA and ECMWF (the European forecast centre), blended 50/50. It has been the main source since 26 Aug.
- **Wind** is GFS, the US weather model. The weather stations confirmed that choice on 16 Sep (the old model read about 0.8 m/s too light at every lead), so we stopped recording the old one. **Tide and water temperature** come from free global datasets.
- **Each spot has its own seabed profile.** The forecast walks the swell in over that seabed until it breaks. That is how the offshore swell becomes surf height.
- **App:** installable, Google sign-in for favorites, push alerts for swells, share button, search-friendly spot pages. The embeddable widget shipped 14 Sep. Live beach cams now follow their stream when YouTube restarts it (15 Sep), so they stop going dark. First full check after the overnight update on 16 Sep.
- **Roadmap:** stages 0, 2 and 3 are built. Stage 4 (a detailed nearshore wave model called SWAN) started as a Southern California pilot on 14 Sep. For now it only records; it doesn't publish.

## How we improve
- **We measure before we change anything.** Buoys score the forecast.
- Every change runs side by side with the old version on the same data. It ships only if it wins.
- Surfer 👍👎 feedback gets logged to tune the things buoys can't see, like the wind effect.

## Compared with Surfline
- **We have no head-to-head scorecard, and can't have one.** Surfline is another forecast, not the truth, and we never take in their data.
- **Side by side by eye:** in Israel our heights track theirs hour by hour, mostly inside their range. Their wind turned out to be plain GFS, so we switched to GFS on 30 Aug.
- **Against buoys, the new blend vs our old source:** ahead in Portugal at every forecast day (height error 0.10 m vs 0.13 m on day 1). Level or slightly ahead in California, level on the US East Coast, **behind in Hawaii**.
- **Where they lead:** a proper nearshore model, cams, human forecasters, years of tuning.
- **Where we lead:** free for the full 15 days, a public rating formula, and a confidence figure shown on every forecast.
- **Honest gap:** buoys only exist in the US and Portugal. Most spots have no ground truth. That includes Israel, where the formula was tuned.

## Weak spots and fixes in flight
1. **The last few km to the beach:** the SWAN pilot. Verdict due around 5 Oct.
2. **Wind at the beach reads too light:** 5 Israeli beach weather stations went live on 14 Sep. First read around 28 Sep.
3. **Spot-count ceiling:** wind is the last source we still pay for in daily request quota per spot (Open-Meteo). With South America we are about 18% over the supplier's stated daily limit. It has never been enforced and the first full update went through clean. The replacement (raw NOAA wind files) gets scored around 26 Sep and removes the limit.
4. **Updates were slow to go live:** each one took about 4.5 hours, and 2 of those were two experiments running before the forecast. They now run after it, and the spots are computed on all four processor cores. Expected: live about 2 hours sooner. First real measurement is the 17:20 update on 17 Sep.
5. **Smaller issues:** the 49 shore directions re-aimed during the South America seeding need one review pass. The confidence figure is still measured on the old wave source. Surf height jumps with small tide changes at about 148 spots. Secondary swells have no peak period.

## Next step
**The 8-week checkpoint ran on 17 Sep. Nothing published changes.**
- The blend is as accurate as the old source on wave height (within 1 cm) and better on direction (3 to 5 degrees). The 26 Aug switch stands.
- Re-tuned blend weights gain under 1 cm and lose a little direction. 50/50 stays.
- The wind choice stands. The old source is still slightly better on day one.
- The held-back seabed fix is withdrawn. At 2,254 spots it would move about 80 spots by more than 10 cm, some up and some down.

**Next:** about 260 spots have a seabed line whose far end sits on another reef, a bank or a lagoon floor, so their height is unreliable (one Fiji spot reads flat in a 1 m swell). List them, sort them by cause, then fix per cause.
