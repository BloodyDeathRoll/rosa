import type { CurrentEntry } from "../types";
import { heightRange, hourOf } from "../format";
import { DirArrow, RatingChip, WindCell } from "./parts";

const WHY_MAX = { size: 40, period: 20, wind: 40 } as const;

export function CurrentCard({ cur }: { cur: CurrentEntry }) {
  const mainSwell = cur.swells.find((s) => s.in_window);
  return (
    <section class="card current" data-bucket={cur.bucket} aria-label="Current conditions">
      <div class="verdict">
        <h2>{cur.phrase}</h2>
        <RatingChip bucket={cur.bucket} rating={cur.rating} />
      </div>
      <p class="numbers">
        <b>{heightRange(cur.h)}</b>
        {mainSwell && (
          <span>
            {mainSwell.h} m @ {mainSwell.period} s{" "}
            <DirArrow from={mainSwell.dir} title={`swell from ${mainSwell.dir}°`} />
          </span>
        )}
        <WindCell wind={cur.wind} />
      </p>
      <p class="water">
        {cur.sst !== null && <span>{cur.sst}°C</span>}
        {cur.wetsuit && <span>{cur.wetsuit}</span>}
        <span class="asof">as of {hourOf(cur.t)}</span>
      </p>
      <details class="why">
        <summary>Why this rating</summary>
        <ul>
          {(Object.keys(WHY_MAX) as (keyof typeof WHY_MAX)[]).map((k) => (
            <li key={k}>
              <span class="why-label">
                {k} {cur.why[k]}/{WHY_MAX[k]}
              </span>
              <span class="meter">
                <i style={`width:${(100 * cur.why[k]) / WHY_MAX[k]}%`} data-bucket={cur.bucket} />
              </span>
            </li>
          ))}
        </ul>
        <p class="why-note">
          Rating adds size (0–40), period (0–20) and wind (0–40). Wind points shrink when
          there's little swell to groom.
        </p>
      </details>
    </section>
  );
}
