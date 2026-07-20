import { useEffect, useState } from "preact/hooks";
import { fetchSpot } from "../api";
import {
  ArrowIcon,
  ChevronLeftIcon,
  MapIcon,
  ShirtIcon,
  ThermometerIcon,
  WavesIcon,
} from "../components/icons";
import { Pill, StarButton } from "../components/parts";
import { ratingVar } from "../conditions";
import { getFavorites, toggleFavorite } from "../favorites";
import { pushRecent } from "../recents";
import {
  arrowRotation,
  cardinal,
  dateOf,
  dayDate,
  dayLabel,
  hourOf,
  knots,
  splitName,
} from "../format";
import { setPendingPin } from "./MapPage";
import { fmtClock, sunTimes } from "../sun";
import { fmtH, fmtTemp, heightUnit, useUnits, type Units } from "../units";
import type { DayEntry, HourEntry, SpotPayload } from "../types";

function qClass(q: number): string {
  return q >= 0.7 ? "q-good" : q >= 0.45 ? "q-fair" : q >= 0.25 ? "q-warn" : "q-poor";
}

const pmOf = (hours: HourEntry[]) =>
  hours.filter((h) => {
    const H = Number(h.t.slice(11, 13));
    return H >= 12 && H <= 18;
  });

/** Size / Period / Wind quality bars for the selected day (mock's bars3). */
function DayBars({ day, hours }: { day: DayEntry; hours: HourEntry[] }) {
  const per = Math.max(0, ...hours.map((h) => h.swells.find((s) => s.in_window)?.period ?? 0));
  const pm = pmOf(hours);
  const pmKts = pm.length > 0 ? Math.max(...pm.map((h) => knots(h.wind.kph))) : 0;
  const bars = [
    { l: "Size", q: Math.min(1, day.h_max[1] / 1.3) },
    { l: "Period", q: Math.min(1, per / 9) },
    { l: "Wind", q: hours.length > 0 ? Math.max(0.12, 1 - pmKts / 22) : 0 },
  ];
  return (
    <div class="why-bars">
      {bars.map((b) => (
        <div class="bar" key={b.l}>
          <span>{b.l}</span>
          <span class="track">
            <i class={qClass(b.q)} style={`width:${Math.round(b.q * 100)}%`} />
          </span>
        </div>
      ))}
    </div>
  );
}

/** Blunt day note in the mock's voice, derived from published day maxima + winds. */
function dayNote(days: DayEntry[], i: number, hours: HourEntry[]): string {
  const d = days[i];
  if (!d) return "";
  const h = d.h_max[1];
  const prev = days[i - 1]?.h_max[1];
  const next = days[i + 1]?.h_max[1];
  if (d.bucket === "FLAT") return "Flat — rest day";
  if (next !== undefined && next >= h * 1.25) return "New swell filling in";
  if (prev !== undefined && prev >= h * 1.25)
    return d.bucket === "POOR" ? "Leftover ripples" : "Fading — morning only";
  const peak = (prev === undefined || h >= prev) && (next === undefined || h >= next);
  if ((d.bucket === "GOOD" || d.bucket === "FIRING") && peak) return "Peak of the swell — go early";
  const am = hours.filter((x) => Number(x.t.slice(11, 13)) < 11);
  const amClean = am.some((x) => x.wind.class !== "onshore" && knots(x.wind.kph) <= 8);
  const pmBlown = pmOf(hours).some((x) => x.wind.class === "onshore" && knots(x.wind.kph) >= 12);
  if (amClean && pmBlown) return "Clean early, blown out by noon";
  if (d.bucket === "POOR") return "Barely waves";
  return "Workable windows";
}

/** Top three GOOD-or-better slots of the selected day, chronological. */
function sessionChips(dayHours: HourEntry[]): HourEntry[] {
  return dayHours
    .filter((h) => h.rating >= 50)
    .sort((a, b) => b.rating - a.rating || b.h_mid - a.h_mid)
    .slice(0, 3)
    .sort((a, b) => (a.t < b.t ? -1 : 1));
}

function chipEnd(h: HourEntry): string {
  return `${String((Number(h.t.slice(11, 13)) + 3) % 24).padStart(2, "0")}:00`;
}

/** Micro-tidal placeholder curve exactly as mocked (M2 sine) — the pipeline
    doesn't publish tides yet; Med spots are sparkline-only by design. */
function TideSection({ nowT, metric }: { nowT: string; metric: boolean }) {
  const pts: string[] = [];
  for (let t = 0; t <= 48; t++) {
    const hr = t / 2;
    const y = 35 - 20 * Math.sin(((hr - 8.2) / 12.42) * 2 * Math.PI);
    pts.push(`${((hr / 24) * 326).toFixed(1)},${y.toFixed(1)}`);
  }
  const line = `M${pts.join(" L")}`;
  const nowX = (
    ((Number(nowT.slice(11, 13)) + Number(nowT.slice(14, 16)) / 60) / 24) *
    326
  ).toFixed(1);
  return (
    <div class="tide-sec">
      <div class="head">
        <span class="eyebrow">Tide</span>
        <span class="note">~0.3 m range — barely matters here</span>
      </div>
      <svg width="358" height="52" viewBox="0 0 326 70" preserveAspectRatio="none">
        <path d={`${line} L326,70 L0,70 Z`} fill="rgba(217,119,86,0.10)" stroke="none" />
        <path d={line} fill="none" stroke="var(--accent)" stroke-width="1.5" />
        <line
          x1={nowX}
          y1="6"
          x2={nowX}
          y2="64"
          stroke="var(--foreground)"
          stroke-width="1"
          stroke-dasharray="2 3"
        />
      </svg>
      <div class="lohi tabular">
        <span class="hi">High 14:20 · {metric ? "0.4 m" : "1.3 ft"}</span>
        <span class="lo">Low 21:05 · {metric ? "0.2 m" : "0.7 ft"}</span>
      </div>
    </div>
  );
}

function HourRow({ h, units }: { h: HourEntry; units: Units }) {
  const swell = h.swells.find((s) => s.in_window) ?? h.swells[0];
  return (
    <div class="hour-grid row">
      <span class="t tabular">{hourOf(h.t)}</span>
      <span
        class="bar"
        style={`background:${h.bucket === "FLAT" ? "var(--border)" : ratingVar(h.bucket)}`}
      />
      <span class="surf">
        <b class="tabular">{fmtH(h.h_mid, units)}</b>
        <small class="tabular">
          {fmtH(h.h[0], units)}–{fmtH(h.h[1], units)}
        </small>
      </span>
      <span class="vec">
        {swell ? (
          <>
            <ArrowIcon rotate={arrowRotation(swell.dir)} />
            <span class="tabular">{Math.round(swell.period)}s</span>
          </>
        ) : (
          <small>—</small>
        )}
      </span>
      <span class="vec">
        <ArrowIcon rotate={arrowRotation(h.wind.dir)} />
        <span class="tabular">
          {knots(h.wind.kph)} <small>{cardinal(h.wind.dir)}</small>
        </span>
      </span>
      <span class="power tabular">{h.energy.toFixed(1)}</span>
      <span class="press tabular">{h.pressure ?? "—"}</span>
    </div>
  );
}

export function SpotPage({ id }: { id: string }) {
  const [data, setData] = useState<SpotPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>(getFavorites);
  const [daySel, setDaySel] = useState(0);
  const units = useUnits();

  useEffect(() => {
    setData(null);
    setError(null);
    setDaySel(0);
    pushRecent(id);
    fetchSpot(id).then(setData, (e: Error) => setError(e.message));
  }, [id]);

  const goBack = () => {
    if (history.length > 1) history.back();
    else location.hash = "#/";
  };

  if (error || !data) {
    return (
      <main class="page">
        <header class="app-head">
          <button class="spot-back" onClick={goBack} aria-label="Back">
            <ChevronLeftIcon />
            <span class="name">…</span>
          </button>
        </header>
        <p class="state">{error ?? "Loading…"}</p>
      </main>
    );
  }

  const { name, region } = splitName(data.spot.name);
  const cur = data.current;
  const days = data.days.slice(0, 7);
  const day = days[daySel] ?? days[0];
  const dayHours = day ? data.hours.filter((h) => dateOf(h.t) === day.date) : [];
  const chips = sessionChips(dayHours);
  const today = data.hours[0] ? dateOf(data.hours[0].t) : "";
  const isFav = favs.includes(id);
  const sun = day
    ? sunTimes(new Date(`${day.date}T12:00:00Z`), data.spot.lat, data.spot.lon)
    : null;

  return (
    <main class="page">
      <header class="app-head" style="padding:0 12px">
        <button class="spot-back" onClick={goBack} aria-label="Back">
          <ChevronLeftIcon />
          <span class="name">
            {name} {region && <span class="region">· {region}</span>}
          </span>
        </button>
        <StarButton on={isFav} name={name} onToggle={() => setFavs(toggleFavorite(id))} />
      </header>

      <div class="spot-main">
        <section class="spot-card">
          <div class="inner">
            <div class="pill-row">
              <Pill bucket={day?.bucket ?? cur.bucket} />
              <span class="est-note tabular">
                estimated · {fmtClock(new Date(data.generated_at), data.spot.timezone)}
              </span>
            </div>
            {day && <DayBars day={day} hours={dayHours} />}
            <div class="sessions">
              <span class="eyebrow">Best sessions</span>
              {chips.length > 0 ? (
                <span class="chips">
                  {chips.map((h) => (
                    <span class="session-chip pill tabular" data-bucket={h.bucket} key={h.t}>
                      {hourOf(h.t)}–{chipEnd(h)}
                    </span>
                  ))}
                </span>
              ) : (
                <span class="none">none worth the paddle</span>
              )}
            </div>
            <div class="temps-row">
              <span>
                <ThermometerIcon />
                <span class="tabular">air {cur.air !== null ? fmtTemp(cur.air, units) : "—"}</span>
              </span>
              <span>
                <WavesIcon />
                <span class="tabular">
                  water {cur.sst !== null ? fmtTemp(cur.sst, units) : "—"}
                </span>
              </span>
              {cur.wetsuit && (
                <span>
                  <ShirtIcon />
                  <span class="suit">{cur.wetsuit}</span>
                </span>
              )}
            </div>
          </div>
          <div class="card-foot">
            <button
              class="accent-link"
              onClick={() => {
                setPendingPin(id);
                location.hash = "#/map";
              }}
            >
              <MapIcon size={14} />
              Show on map →
            </button>
          </div>
        </section>

        <div class="day-pills">
          {days.map((d, i) => (
            <button key={d.date} class={i === daySel ? "on" : ""} onClick={() => setDaySel(i)}>
              <span class="l">{dayLabel(d.date, today)}</span>
              <span class="dot" style={`background:${ratingVar(d.bucket)}`} />
            </button>
          ))}
        </div>

        {day && (
          <>
            <div class="day-title">
              <b>
                {dayLabel(day.date, today)} · {dayDate(day.date)}
              </b>
              <span>{dayNote(days, daySel, dayHours)}</span>
            </div>
            <div class="hour-grid head" aria-hidden="true">
              <span />
              <span />
              <span>surf {heightUnit(units)}</span>
              <span>swell</span>
              <span>wind kt</span>
              <span>kW/m</span>
              <span>hPa</span>
            </div>
            {dayHours.map((h) => (
              <HourRow key={h.t} h={h} units={units} />
            ))}
            {dayHours.length === 0 && (
              <p class="state">Beyond the model horizon — no hourly detail yet.</p>
            )}
          </>
        )}

        <TideSection nowT={cur.t} metric={units.height === "m"} />

        {sun && (
          <div class="sun-row">
            <span>
              <span class="eyebrow">First light</span>
              <b class="tabular">{fmtClock(sun.firstLight, data.spot.timezone)}</b>
            </span>
            <span>
              <span class="eyebrow">Sunrise</span>
              <b class="tabular">{fmtClock(sun.sunrise, data.spot.timezone)}</b>
            </span>
            <span>
              <span class="eyebrow">Sunset</span>
              <b class="tabular">{fmtClock(sun.sunset, data.spot.timezone)}</b>
            </span>
            <span>
              <span class="eyebrow">Last light</span>
              <b class="tabular">{fmtClock(sun.lastLight, data.spot.timezone)}</b>
            </span>
          </div>
        )}
      </div>
    </main>
  );
}
