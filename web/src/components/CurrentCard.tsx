import type { CurrentEntry } from "../types";
import { cardinal, heightRange, hourOf } from "../format";
import { DirArrow, RatingChip } from "./parts";

const WHY_MAX = { size: 40, period: 20, wind: 40 } as const;

export function CurrentCard({ name, cur }: { name: string; cur: CurrentEntry }) {
  const swell = cur.swells.find((s) => s.in_window) ?? cur.swells[0];
  return (
    <section class="card current" data-bucket={cur.bucket} aria-label="Current conditions">
      <div class="verdict">
        <h2>{name}</h2>
        <RatingChip bucket={cur.bucket} />
      </div>

      <div class="stats">
        <span class="stat">
          <b>{cur.h_mid}</b>
          <small>{heightRange(cur.h)}</small>
          <em>surf m</em>
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
        <span class="stat">
          <b>{cur.energy}</b>
          <small>kW/m</small>
          <em>energy</em>
        </span>
        <span class="stat">
          <b>{cur.pressure ?? "—"}</b>
          <small>mb</small>
          <em>pressure</em>
        </span>
      </div>

      <p class="water">
        {cur.sst !== null && <span>{cur.sst}°C</span>}
        {cur.wetsuit && <span>{cur.wetsuit}</span>}
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
