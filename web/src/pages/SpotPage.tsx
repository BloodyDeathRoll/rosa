import type { VNode } from "preact";
import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import { fetchIndex, fetchSpot } from "../api";
import {
  ChevronLeftIcon,
  MapIcon,
  ShirtIcon,
  SwellDirIcon,
  ThermometerIcon,
  WavesIcon,
  WindDirIcon,
} from "../components/icons";
import { DateBar } from "../components/DateBar";
import { DayCarousel } from "../components/DayCarousel";
import { Pill, StarButton } from "../components/parts";
import { ratingVar } from "../conditions";
import { getFavorites, toggleFavorite } from "../favorites";
import { pushRecent } from "../recents";
import { signalReady } from "../splash";
import {
  arrowRotation,
  cardinal,
  dateOf,
  dayDate,
  dayLabel,
  hourOf,
  knots,
  splitName,
  windClassWord,
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

/** Minutes-of-day (spot-local) of an hourly slot's start, e.g. "…T03:00" → 180. */
const slotStartMin = (h: HourEntry) =>
  Number(h.t.slice(11, 13)) * 60 + Number(h.t.slice(14, 16));

/** Top three GOOD-or-better slots of the selected day, chronological — restricted
    to slots that begin in daylight (first light → last light), so we never call a
    pre-dawn or post-dusk hour a "best session". Bounds are minutes-of-day, spot-local. */
function sessionChips(
  dayHours: HourEntry[],
  firstLightMin: number,
  lastLightMin: number
): HourEntry[] {
  return dayHours
    .filter((h) => h.rating >= 50)
    .filter((h) => {
      const m = slotStartMin(h);
      return m >= firstLightMin && m < lastLightMin;
    })
    .sort((a, b) => b.rating - a.rating || b.h_mid - a.h_mid)
    .slice(0, 3)
    .sort((a, b) => (a.t < b.t ? -1 : 1));
}


function HourRow({
  h,
  units,
  best,
  first,
  last,
  label,
}: {
  h: HourEntry;
  units: Units;
  best?: boolean;
  first?: boolean;
  last?: boolean;
  label?: string;
}) {
  const swell = h.swells.find((s) => s.in_window) ?? h.swells[0];
  return (
    <div
      class={`hour-grid row${best ? " best" : ""}${first ? " best-first" : ""}${
        last ? " best-last" : ""
      }`}
    >
      {label && <span class="best-tag">{label}</span>}
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
      <span class="vec swell-cell">
        {swell ? (
          <>
            <span class="top">
              <SwellDirIcon rotate={arrowRotation(swell.dir)} />
              <b class="tabular">{Math.round(swell.period)}s</b>
            </span>
            <small class="tabular">{cardinal(swell.dir)}</small>
          </>
        ) : (
          <small>—</small>
        )}
      </span>
      <span class={`wind-cell wc-${h.wind.class}`}>
        <span class="top">
          <WindDirIcon rotate={arrowRotation(h.wind.dir)} />
          <b class="tabular">{knots(h.wind.kph)}</b>
        </span>
        <small class="cardinal tabular">{cardinal(h.wind.dir)}</small>
        <small class="wclass">{windClassWord(h.wind.class)}</small>
      </span>
      <span class="power tabular">{h.energy.toFixed(1)}</span>
      <span class="press tabular">{h.pressure ?? "—"}</span>
    </div>
  );
}

/** Horizontal spot chips (design 1a): freely draggable — touch scroll native,
    mouse drag via pointer events. Never auto-scrolls: tapping a chip changes
    the spot but leaves the strip where the user left it. */
function SpotSwitcher({ spots, currentId }: { spots: [string, IndexEntry][]; currentId: string }) {
  const trackRef = useRef<HTMLDivElement>(null);
  // pointer drag state — mouse only; touch uses native overflow-x pan
  const drag = useRef({ down: false, startX: 0, startScroll: 0, moved: false });

  const onPointerDown = (e: PointerEvent) => {
    if (e.pointerType !== "mouse") return;
    const t = trackRef.current;
    if (!t) return;
    drag.current = { down: true, startX: e.clientX, startScroll: t.scrollLeft, moved: false };
  };
  const onPointerMove = (e: PointerEvent) => {
    if (!drag.current.down) return;
    const t = trackRef.current;
    if (!t) return;
    const dx = e.clientX - drag.current.startX;
    if (Math.abs(dx) > 3) drag.current.moved = true;
    t.scrollLeft = drag.current.startScroll - dx;
  };
  const onPointerUp = () => {
    drag.current.down = false;
    // clear moved on next tick so the click handler can still see it
    setTimeout(() => {
      drag.current.moved = false;
    }, 0);
  };

  return (
    <div class="spot-switch">
      <div
        class="track"
        ref={trackRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onPointerLeave={onPointerUp}
      >
        {spots.map(([sid, e]) => {
          const on = sid === currentId;
          return (
            <a
              key={sid}
              class={`schip${on ? " on" : ""}`}
              href={`#/spot/${sid}`}
              aria-current={on ? "page" : undefined}
              onClick={(ev) => {
                if (drag.current.moved) ev.preventDefault();
              }}
            >
              {splitName(e.name).name}
            </a>
          );
        })}
      </div>
    </div>
  );
}

const NEAR_RADIUS_KM = 20; // switcher outer bound
const NEAR_MAX = 8; // ...capped to this many nearest spots

export function SpotPage({ id }: { id: string }) {
  const [data, setData] = useState<SpotPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>(getFavorites);
  const [daySel, setDaySel] = useState(0);
  const [liveDay, setLiveDay] = useState(0);
  const [spots, setSpots] = useState<[string, IndexEntry][]>([]);
  const units = useUnits();
  // commit a day: settle both the highlight (live) and the content (daySel)
  const commitDay = useCallback((i: number) => {
    setDaySel(i);
    setLiveDay(i);
  }, []);

  useEffect(() => {
    setData(null);
    setError(null);
    setDaySel(0);
    setLiveDay(0);
    pushRecent(id);
    fetchSpot(id)
      .then(setData, (e: Error) => setError(e.message))
      .finally(signalReady);
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

  // switcher + swipe: the 8 spots nearest the current one (within 20 km),
  // shown north→south
  const curEntry = spots.find(([sid]) => sid === id)?.[1];
  const nearSpots = curEntry
    ? spots
        .map(([sid, e]) => ({
          entry: [sid, e] as [string, IndexEntry],
          km: distanceKm({ lat: curEntry.lat, lon: curEntry.lon }, { lat: e.lat, lon: e.lon }),
        }))
        .filter(({ km }) => km <= NEAR_RADIUS_KM)
        .sort((a, b) => a.km - b.km)
        .slice(0, NEAR_MAX)
        .map(({ entry }) => entry)
        .sort(([, a], [, b]) => b.lat - a.lat)
    : [];

  // the date bar + carousel both drive the selected day
  const allDays = data?.days ?? [];
  const daySelClamped = Math.min(daySel, Math.max(0, allDays.length - 1));
  const liveClamped = Math.min(liveDay, Math.max(0, allDays.length - 1));

  // Memoize the carousel vnode: a live scrub re-renders the parent to move the date
  // highlight, but the identical vnode reference lets Preact skip re-diffing the heavy
  // day panels (hour grid, tide, sun) — only the committed `daySelClamped` rebuilds it.
  const carousel = useMemo(() => {
    if (!data) return null;
    const days = data.days;
    const cur = data.current;
    const today = data.hours[0] ? dateOf(data.hours[0].t) : "";
    // one full-width panel per day; the carousel drags between them
    const dayPanel = (i: number) => {
      const day = days[i];
      if (!day) return null;
      const dayHours = data.hours.filter((h) => dateOf(h.t) === day.date);
      const sun = sunTimes(new Date(`${day.date}T12:00:00Z`), data.spot.lat, data.spot.lon);
      // daylight bounds in spot-local minutes so pre-dawn/post-dusk slots are excluded
      const toMin = (d: Date) => {
        const [hh, mm] = fmtClock(d, data.spot.timezone).split(":");
        return Number(hh) * 60 + Number(mm);
      };
      const chips = sessionChips(dayHours, toMin(sun.firstLight), toMin(sun.lastLight));
      // best-session slots → tinted rows, with a "Best session" tag overlaid on the
      // first row of each contiguous run (top-right, just under the row's top border)
      const bestSet = new Set(chips.map((c) => c.t));
      const hourRows: VNode[] = [];
      for (let i = 0; i < dayHours.length; i++) {
        const h = dayHours[i]!;
        const isBest = bestSet.has(h.t);
        const prevBest = i > 0 && bestSet.has(dayHours[i - 1]!.t);
        const nextBest = i + 1 < dayHours.length && bestSet.has(dayHours[i + 1]!.t);
        hourRows.push(
          <HourRow
            key={h.t}
            h={h}
            units={units}
            best={isBest}
            first={isBest && !prevBest}
            last={isBest && !nextBest}
            label={isBest && !prevBest ? "Best session" : undefined}
          />
        );
      }
      return (
        <div class="spot-main">
          <section class="spot-card">
            <div class="rc-left">
              <Pill bucket={day.bucket} />
              <DayBars day={day} hours={dayHours} />
            </div>
            <div class="rc-right">
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
              <div class="rc-temps">
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
          </section>

          <div class="day-title">
            <b>
              {dayLabel(day.date, today)} · {dayDate(day.date)}
            </b>
            <span>{dayNote(days, i, dayHours)}</span>
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
          {hourRows}
          {dayHours.length === 0 && (
            <p class="state">Beyond the model horizon — no hourly detail yet.</p>
          )}

          <TideSection nowT={cur.t} metric={units.height === "m"} />

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
        </div>
      );
    };
    return (
      <DayCarousel
        count={days.length}
        selected={daySelClamped}
        onSelect={commitDay}
        onScrub={setLiveDay}
        renderPanel={dayPanel}
      />
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, units, daySelClamped, commitDay]);

  // Top bar: back arrow · spot switcher (masked, fills the middle) · fav star.
  const topBar = (
    <div class="spot-top">
      <button class="spot-back" onClick={goBack} aria-label="Back">
        <ChevronLeftIcon />
      </button>
      {nearSpots.length > 1 && <SpotSwitcher spots={nearSpots} currentId={id} />}
      {data && (
        <StarButton
          on={favs.includes(id)}
          name={splitName(data.spot.name).name}
          onToggle={() => setFavs(toggleFavorite(id))}
        />
      )}
    </div>
  );

  if (error || !data) {
    return (
      <main class="page">
        <div class="spot-sticky">{topBar}</div>
        <p class="state">{error ?? "Loading…"}</p>
      </main>
    );
  }

  const days = data.days;
  const today = data.hours[0] ? dateOf(data.hours[0].t) : "";

  return (
    <main class="page">
      <div class="spot-sticky">
        {topBar}
        <DateBar
          dates={days.map((d) => d.date)}
          buckets={days.map((d) => d.bucket)}
          selected={daySelClamped}
          live={liveClamped}
          today={today}
          onSelect={commitDay}
        />
      </div>
      {carousel}
    </main>
  );
}
