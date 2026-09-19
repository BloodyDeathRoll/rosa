# Rosa progress

Last updated: 17 Sep 2026. Updated at every `/session-off` (project skill `.claude/skills/session-off`).

## Status now
- **Live and healthy.** 2,254 spots worldwide, a 15-day forecast, updated 4 times a day. Last update checked: 07:29 on 17 Sep.
- **South America is in (16 Sep):** Chile, Ecuador, Uruguay, Argentina and the three missing Brazilian states - 307 new spots, every pin checked on satellite photos.
- **Wave data** comes from NOAA and ECMWF (the European forecast centre), blended 50/50. It has been the main source since 26 Aug.
- **Wind** is GFS, the US weather model. The weather stations confirmed that choice on 16 Sep (the old model read about 0.8 m/s too light at every lead), so we stopped recording the old one. **Tide and water temperature** come from free global datasets.
- **Each spot has its own seabed profile.** The forecast walks the swell in over that seabed until it breaks. That is how the offshore swell becomes surf height.
- **App:** installable, Google sign-in for favorites, push alerts for swells, share button, search-friendly spot pages. The embeddable widget shipped 14 Sep. On 17 Sep: the home screen greets signed-in surfers by first name, and each column of the hourly table (surf, swell, wind, energy) has its own help icon that opens the right part of the "Reading the forecast" page. Live beach cams now follow their stream when YouTube restarts it (15 Sep), so they stop going dark. First full check after the overnight update on 16 Sep.
- **Roadmap:** stages 0, 2 and 3 are built. Stage 4 (a detailed nearshore wave model called SWAN) started as a Southern California pilot on 14 Sep. For now it only records; it doesn't publish.

## How we improve
- **We measure before we change anything.** Buoys score the forecast.
- Every change runs side by side with the old version on the same data. It ships only if it wins.
- Surfer 👍👎 feedback gets logged to tune the things buoys can't see, like the wind effect.

## Compared with Surfline
- **We have no head-to-head scorecard, and can't have one.** Surfline is another forecast, not the truth, and we never take in their data.
- **Side by side by eye:** in Israel our heights track theirs hour by hour, mostly inside their range. Their wind turned out to be plain GFS, so we switched to GFS on 30 Aug.
- **Against buoys, the new blend vs our old source (8 weeks of data, read 17 Sep):** level on wave height everywhere (within 1 cm), better on wave direction by 3 to 5 degrees. Hawaii, which used to favour the old source, is now level. Portugal has too little buoy data to read.
- **Where they lead:** a proper nearshore model, cams, human forecasters, years of tuning.
- **Where we lead:** free for the full 15 days, a public rating formula, and a confidence figure shown on every forecast.
- **Honest gap:** buoys only exist in the US and Portugal. Most spots have no ground truth. That includes Israel, where the formula was tuned.

## Weak spots and fixes in flight
1. **The last few km to the beach:** the SWAN pilot. Verdict due around 5 Oct.
2. **Wind at the beach reads too light:** 5 Israeli beach weather stations went live on 14 Sep. First read around 28 Sep.
3. **Spot-count ceiling:** wind is the last source we still pay for in daily request quota per spot (Open-Meteo). With South America we are about 18% over the supplier's stated daily limit. It has never been enforced. The replacement (raw NOAA wind files) gets scored around 26 Sep and removes the limit.
4. **Updates were slow to go live:** about 4.5 hours each. The faster order starts with the 17:20 update on 17 Sep. Expected: live about 2 hours sooner. Not measured yet.
5. **Bad seabed lines (found 17 Sep):** at about 150 spots the seabed line the forecast walks in along is unreliable. 10 were aimed wrong and are fixed (4 of them showed a flat sea during a real swell). About 128 sit on shallow shelves where the free depth map is too noisy and need measured depth data. 9 cross a reef or a map error and are still open.
6. **Google Play app (closed test since 16 Sep):** it is the same Rosa as the installed web app, so a phone with both just has two icons. Since 17 Sep the web app stops offering to install once the Play app is there, and tells an existing install once that it is the spare. Not tested on a real phone yet. Sending Chrome's install button to the store waits until the store page is public. 12 testers still need to opt in before the 14-day clock starts.
7. **One tester could not sign in (17 Sep, 11:28):** the app said Rosa could not be reached. Everything on our side checked out and another user signed in fine that morning. Cause unknown. If it repeats we watch the sign-in service live while they try.
8. **Smaller issues:** the 49 shore directions re-aimed during the South America seeding need one review pass. The confidence figure is still measured on the old wave source. Surf height jumps with small tide changes at about 148 spots. Secondary swells have no peak period.

## Next step
**After the 17:20 update on 17 Sep:** measure how long it took to go live, and check the 10 re-aimed spots on the live site.

The 8-week checkpoint ran on 17 Sep and changed nothing published: the blend stays, the 50/50 weights stay, the wind choice stays, and one planned seabed fix was dropped because it would have moved about 80 spots by more than 10 cm in both directions.

Then the dated reads: NOAA wind 26 Sep, beach wind stations 28 Sep, SWAN pilot 5 Oct.
