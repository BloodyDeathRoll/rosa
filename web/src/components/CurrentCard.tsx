import type { CurrentEntry } from "../types";
import { verdictFor } from "../conditions";
import { cardinal, hourOf } from "../format";
import { fmtH, fmtRange, fmtTemp, heightUnit, useUnits } from "../units";
import { DirArrow, RatingChip } from "./parts";
import { ShirtIcon, WetsuitIcon } from "./icons";

const WHY_MAX = { size: 40, period: 20, wind: 40 } as const;

export function CurrentCard({ name, cur }: { name: string; cur: CurrentEntry }) {
  const units = useUnits();
  const swell = cur.swells.find((s) => s.in_window) ?? cur.swells[0];
  const isRashguard = cur.wetsuit?.includes("rashguard") ?? false;
  return (
    <section class="card current" data-bucket={cur.bucket} aria-label="Current conditions">
      <div class="verdict">
        <h2>{name}</h2>
        <RatingChip bucket={cur.bucket} />
      </div>

      <p class="verdict-line" data-bucket={cur.bucket}>
        {verdictFor(cur.bucket, `${name}${cur.t.slice(0, 10)}`)}
      </p>

      <div class="stats stats-3">
        <span class="stat">
          <b>{fmtH(cur.h_mid, units)}</b>
          <small>{fmtRange(cur.h, units, false)}</small>
          <em>surf {heightUnit(units)}</em>
        </span>
        <span class="stat">
          <b>{swell ? `${Math.round(swell.period)}s` : "—"}</b>
          <small>{swell ? `${Math.round(swell.dir)}°` : "no swell"}</small>
          <em>swell</em>
        </span>
        <span class="stat" data-windclass={cur.wind.class}>
          <b>
            <DirArrow from={cur.wind.dir} title={`wind from ${cur.wind.dir}° (${cardinal(cur.wind.dir)})`} />
            {Math.round(cur.wind.kph)}
          </b>
          <small>{cur.wind.class === "cross-shore" ? "cross" : cur.wind.class}</small>
          <em>wind kph</em>
        </span>
      </div>

      <p class="water">
        {cur.air !== null && <span>{fmtTemp(cur.air, units)} air</span>}
        {cur.sst !== null && <span>{fmtTemp(cur.sst, units)} water</span>}
        {cur.wetsuit && (
          <span class="suit">
            {isRashguard ? <ShirtIcon /> : <WetsuitIcon />}
            {cur.wetsuit}
          </span>
        )}
        <span class="asof">as of {hourOf(cur.t)}</span>
      </p>

      <div class="why">
        <ul>
          {(Object.keys(WHY_MAX) as (keyof typeof WHY_MAX)[]).map((k) => (
            <li key={k}>
              <span class="why-label">
                {k} {Math.round(cur.why[k])}/{WHY_MAX[k]}
              </span>
              <span class="meter">
                <i style={`width:${(100 * cur.why[k]) / WHY_MAX[k]}%`} data-bucket={cur.bucket} />
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
