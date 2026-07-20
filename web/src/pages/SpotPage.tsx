import { useEffect, useRef, useState } from "preact/hooks";
import { fetchIndex, fetchSpot } from "../api";
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
import { distanceKm } from "../geo";
import { TideSection } from "../components/TideSection";
import { setPendingPin } from "./MapPage";
import { fmtClock, sunTimes } from "../sun";
import { fmtH, fmtTemp, heightUnit, useUnits, type Units } from "../units";
import type { DayEntry, HourEntry, IndexEntry, SpotPayload } from "../types";

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
        <b class="tabular">
          {fmtH(h.h[0], units)}–{fmtH(h.h[1], units)}
        </b>
        <small class="tabular">{fmtH(h.h_mid, units)}</small>
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

/** Horizontal spot chips (design 1a): selected in the dark accent, centered;
    tap to jump. Swiping is handled at the screen level in SpotPage. */
function SpotSwitcher({ spots, currentId }: { spots: [string, IndexEntry][]; currentId: string }) {
  const selRef = useRef<HTMLAnchorElement>(null);
  useEffect(() => {
    // pin the selected spot to the left edge of the strip
    selRef.current?.scrollIntoView({ inline: "start", block: "nearest", behavior: "smooth" });
  }, [currentId]);
  return (
    <div class="spot-switch">
      <div class="track">
        {spots.map(([sid, e]) => {
          const on = sid === currentId;
          return (
            <a
              key={sid}
              ref={on ? selRef : undefined}
              class={`schip${on ? " on" : ""}`}
              href={`#/spot/${sid}`}
              aria-current={on ? "page" : undefined}
            >
              {splitName(e.name).name}
            </a>
          );
        })}
      </div>
    </div>
  );
}

const SWIPE_MIN = 45; // px of horizontal travel before a swipe changes spot
const NEAR_RADIUS_KM = 20; // switcher + swipe reach

export function SpotPage({ id }: { id: string }) {
  const [data, setData] = useState<SpotPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>(getFavorites);
  const [daySel, setDaySel] = useState(0);
  const [spots, setSpots] = useState<[string, IndexEntry][]>([]);
  const swipeStart = useRef<{ x: number; y: number } | null>(null);
  const navDir = useRef(0); // -1 north / +1 south — drives the slide-in direction
  const units = useUnits();

  useEffect(() => {
    setData(null);
    setError(null);
    setDaySel(0);
    pushRecent(id);
    fetchSpot(id).then(setData, (e: Error) => setError(e.message));
  }, [id]);

  useEffect(() => {
    // north→south ordering, same as the map drawer's swipe order
    fetchIndex().then(
      (idx) => setSpots(Object.entries(idx.spots).sort(([, a], [, b]) => b.lat - a.lat)),
      () => undefined
    );
  }, []);

  const goBack = () => {
    location.hash = "#/";
  };

  // switcher + swipe are limited to spots within 20 km of the current one
  const curEntry = spots.find(([sid]) => sid === id)?.[1];
  const nearSpots = curEntry
    ? spots.filter(
        ([, e]) =>
          distanceKm({ lat: curEntry.lat, lon: curEntry.lon }, { lat: e.lat, lon: e.lon }) <=
          NEAR_RADIUS_KM
      )
    : [];
  const idx = nearSpots.findIndex(([sid]) => sid === id);
  const step = (delta: number) => {
    const next = nearSpots[idx + delta];
    if (!next) return;
    navDir.current = delta;
    location.hash = `#/spot/${next[0]}`;
  };

  const onPointerDown = (e: PointerEvent) => {
    swipeStart.current = { x: e.clientX, y: e.clientY };
  };
  const onPointerUp = (e: PointerEvent) => {
    const s = swipeStart.current;
    swipeStart.current = null;
    if (!s) return;
    const dx = e.clientX - s.x;
    const dy = e.clientY - s.y;
    if (Math.abs(dx) < SWIPE_MIN || Math.abs(dx) <= Math.abs(dy)) return;
    step(dx < 0 ? 1 : -1); // swipe left → next (south), right → prev (north)
  };

  const header = (
    <header class="app-head spot-head-min">
      <button class="spot-back" onClick={goBack} aria-label="Back">
        <ChevronLeftIcon />
      </button>
      {data && (
        <StarButton
          on={favs.includes(id)}
          name={splitName(data.spot.name).name}
          onToggle={() => setFavs(toggleFavorite(id))}
        />
      )}
    </header>
  );

  if (error || !data) {
    return (
      <main class="page">
        {header}
        {nearSpots.length > 1 && <SpotSwitcher spots={nearSpots} currentId={id} />}
        <p class="state">{error ?? "Loading…"}</p>
      </main>
    );
  }

  const cur = data.current;
  const days = data.days.slice(0, 7);
  const day = days[daySel] ?? days[0];
  const dayHours = day ? data.hours.filter((h) => dateOf(h.t) === day.date) : [];
  const chips = sessionChips(dayHours);
  const today = data.hours[0] ? dateOf(data.hours[0].t) : "";
  const sun = day
    ? sunTimes(new Date(`${day.date}T12:00:00Z`), data.spot.lat, data.spot.lon)
    : null;
  const dirClass =
    navDir.current === 1 ? "from-right" : navDir.current === -1 ? "from-left" : "";

  return (
    <main class="page">
      {header}
      {nearSpots.length > 1 && <SpotSwitcher spots={nearSpots} currentId={id} />}
      <div class="spot-swipe" onPointerDown={onPointerDown} onPointerUp={onPointerUp}>
        <div class={`spot-main spot-view ${dirClass}`} key={id}>
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
      </div>
    </main>
  );
}
