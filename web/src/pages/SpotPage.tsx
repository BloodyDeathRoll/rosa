import type { VNode } from "preact";
import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import { fetchIndex, fetchSpot } from "../api";
import {
  ChevronLeftIcon,
  InfoIcon,
  MapIcon,
  ShirtIcon,
  SwellDirIcon,
  ThermometerIcon,
  WavesIcon,
  WindDirIcon,
} from "../components/icons";
import { DayScrubber } from "../components/CoastChart";
import { Pill, StarButton } from "../components/parts";
import { ratingVar } from "../conditions";
import { getFavorites, toggleFavorite } from "../favorites";
import { stashView } from "../feedback";
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
  todayIn,
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
  // PEAK period, matching every other swell readout (see CLAUDE.md §UI "display != scoring").
  // Caveat: the `per / 9` scale below was set against MEAN periods, so it now saturates on
  // ordinary days - rescale (~/13) before reading much into a full Period bar.
  const per = Math.max(
    0,
    ...hours.map((h) => {
      const s = h.swells.find((x) => x.in_window);
      return s ? (s.peak_period ?? s.period) : 0;
    })
  );
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
  if (d.bucket === "FLAT") return "Flat - rest day";
  if (next !== undefined && next >= h * 1.25) return "New swell filling in";
  if (prev !== undefined && prev >= h * 1.25)
    return d.bucket === "POOR" ? "Leftover ripples" : "Fading - morning only";
  const peak = (prev === undefined || h >= prev) && (next === undefined || h >= next);
  if ((d.bucket === "GOOD" || d.bucket === "FIRING") && peak) return "Peak of the swell - go early";
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

/** Top three GOOD-or-better slots of the selected day, chronological - restricted
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


/** Live cam, first thing on the page when a spot has one.
 *
 * Embedded through YouTube's own iframe player - the only way a cam is allowed into Rosa
 * (CLAUDE.md: never scrape a stream, never touch a competitor's). The credit under the
 * frame is the acknowledgement that permission implies, and it links back to the channel.
 * `loading="lazy"` keeps the player off the wire until it scrolls in, so the sub-2 s first
 * load target survives; nothing here blocks the forecast rendering. */
function CamEmbed({ cam }: { cam?: SpotPayload["spot"]["cam"] }) {
  if (!cam) return null;
  return (
    <section class="cam">
      <div class="cam-frame">
        <iframe
          // autoplay muted is what strips the embed back to the play bar: the title
          // bar, channel avatar, big play button and "Watch on YouTube" overlay all
          // belong to the unstarted state and have no parameter to turn them off.
          // Muted is also the only autoplay mobile browsers allow.
          src={
            `https://www.youtube-nocookie.com/embed/${cam.yt}` +
            `?rel=0&playsinline=1&autoplay=1&mute=1&modestbranding=1&iv_load_policy=3`
          }
          title="Live cam"
          loading="lazy"
          allow="autoplay; accelerometer; encrypted-media; gyroscope; picture-in-picture; fullscreen"
          allowFullScreen
          frameBorder="0"
        />
      </div>
      <p class="cam-credit">
        Live cam by{" "}
        <a href={cam.by_url} target="_blank" rel="noopener noreferrer">
          {cam.by}
        </a>{" "}
        on YouTube{cam.note ? ` - ${cam.note}` : ""}
      </p>
    </section>
  );
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
          {fmtH(h.h[0], units)}-{fmtH(h.h[1], units)}
        </b>
        <small class="tabular">{fmtH(h.h_mid, units)}</small>
      </span>
      <span class="vec swell-cell">
        {swell ? (
          <>
            <span class="top">
              <SwellDirIcon rotate={arrowRotation(swell.dir)} />
              {/* Peak period, the number surf reports quote ("3ft @ 8s") and the one the
                  kJ column is computed from; mean period only where no peak is published. */}
              <b class="tabular">{Math.round(swell.peak_period ?? swell.period)}s</b>
            </span>
            <small class="tabular">{cardinal(swell.dir)}</small>
          </>
        ) : (
          <small>-</small>
        )}
      </span>
      <span class={`wind-cell wc-${h.wind.class}`}>
        <span class="top">
          <WindDirIcon rotate={arrowRotation(h.wind.dir)} />
          <b class="tabular">{knots(h.wind.kph)}</b>
          <small class="cardinal tabular">{cardinal(h.wind.dir)}</small>
        </span>
        <small class="wclass">{windClassWord(h.wind.class)}</small>
      </span>
      <span class="pp">
        <b class="power tabular">{Math.round(h.energy_kj)}</b>
        <small class="press tabular">{h.pressure ?? "-"}</small>
      </span>
    </div>
  );
}

/** Horizontal spot chips (design 1a): freely draggable - touch scroll native,
    mouse drag via pointer events. Never auto-scrolls: tapping a chip changes
    the spot but leaves the strip where the user left it. */
function SpotSwitcher({ spots, currentId }: { spots: [string, IndexEntry][]; currentId: string }) {
  const trackRef = useRef<HTMLDivElement>(null);
  // pointer drag state - mouse only; touch uses native overflow-x pan
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

// Selected date carried across spot→spot navigation (the switcher chips keep
// SpotPage mounted, so this survives the id change). Cleared on unmount, so
// arriving fresh from Home/Map/Favorites still opens on today.
let stickyDate: string | null = null;

export function SpotPage({ id }: { id: string }) {
  const [data, setData] = useState<SpotPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>(getFavorites);
  const [daySel, setDaySel] = useState(0);
  const [liveDay, setLiveDay] = useState(0);
  const [condensed, setCondensed] = useState(false);
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
    pushRecent(id);
    fetchSpot(id)
      .then((d) => {
        // The date bar always starts at the spot's current date - never show days
        // that are already in the past (the payload may be a run or two stale).
        const today = todayIn(d.spot.timezone);
        const future = d.days.filter((day) => day.date >= today);
        const data = future.length ? { ...d, days: future } : d;
        setData(data);
        // keep the previously selected date if it exists in this spot's range,
        // otherwise fall back to today (a ?ev= story link overrides below)
        const idx = stickyDate ? data.days.findIndex((day) => day.date === stickyDate) : -1;
        const start = idx >= 0 ? idx : 0;
        setDaySel(start);
        setLiveDay(start);
        // remember today's promise - tomorrow's open may ask "was the call right?"
        stashView(data);
      }, (e: Error) => setError(e.message))
      .finally(signalReady);
  }, [id]);

  // A push notification's link (#/spot/id?ev=YYYY-MM-DD) opens on the swell's
  // peak day. Reacts to hashchange too: landing in an already-open app is a
  // hash-only change - no reload, no remount - and must still jump the day.
  useEffect(() => {
    const apply = () => {
      const evDate = /[?&]ev=(\d{4}-\d{2}-\d{2})/.exec(location.hash)?.[1];
      if (!evDate || !data) return;
      const i = data.days.findIndex((day) => day.date === evDate);
      if (i >= 0) commitDay(i);
    };
    apply();
    addEventListener("hashchange", apply);
    return () => removeEventListener("hashchange", apply);
  }, [data, commitDay]);

  // remember the committed date so it carries to the next spot; forget it when
  // leaving the spot screen entirely (unmount) so Home/Map open on today
  useEffect(() => {
    const days = data?.days;
    if (!days || days.length === 0) return;
    const i = Math.min(Math.max(daySel, 0), days.length - 1);
    stickyDate = days[i]?.date ?? stickyDate;
  }, [daySel, data]);
  useEffect(() => () => {
    stickyDate = null;
  }, []);

  // Collapse the scrubber's bars once the page scrolls into the forecast, leaving
  // just the compact date row pinned. Wide hysteresis (collapse at 72, only
  // re-expand near the very top, under 8) plus `overflow-anchor: none` on <html>
  // keeps the collapse from feeding back into scrollY and blinking.
  useEffect(() => {
    const onScroll = () => {
      const y = window.scrollY || document.documentElement.scrollTop;
      setCondensed((c) => (c ? y > 8 : y > 72));
    };
    onScroll();
    addEventListener("scroll", onScroll, { passive: true });
    return () => removeEventListener("scroll", onScroll);
  }, []);

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

  // switcher: the user's favorites (north→south); if none are recorded, fall
  // back to the 8 spots nearest the current one (within 20 km).
  const curEntry = spots.find(([sid]) => sid === id)?.[1];
  const favSpots = spots
    .filter(([sid]) => favs.includes(sid))
    .sort(([, a], [, b]) => b.lat - a.lat);
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
  const switcherSpots = favSpots.length > 0 ? favSpots : nearSpots;

  // the day scrubber drives the selected/live day; the panel below follows liveDay
  const allDays = data?.days ?? [];
  const daySelClamped = Math.min(daySel, Math.max(0, allDays.length - 1));
  const liveClamped = Math.min(liveDay, Math.max(0, allDays.length - 1));

  // The forecast for the live-scrubbed day. It rebuilds the instant the strip's
  // centered column changes (keyed on liveDay) - no second scroller and no
  // animation, so the data can't lag behind the date/bars or desync from them.
  const panel = useMemo(() => {
    if (!data) return null;
    const days = data.days;
    const cur = data.current;
    const today = todayIn(data.spot.timezone);
    const i = Math.min(Math.max(liveDay, 0), days.length - 1);
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
          <CamEmbed cam={data.spot.cam} />
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
                Map
              </button>
              <div class="rc-temps">
                <span>
                  <ThermometerIcon />
                  <span class="tabular">air {cur.air !== null ? fmtTemp(cur.air, units) : "-"}</span>
                </span>
                <span>
                  <WavesIcon />
                  <span class="tabular">
                    water {cur.sst !== null ? fmtTemp(cur.sst, units) : "-"}
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
          <div class="hour-grid head">
            <span aria-hidden="true" />
            {/* Sits over the rating rail's 6px column; the icon overhangs it, centred. */}
            <a class="grid-info" href="#/about/reading" aria-label="What these numbers mean">
              <InfoIcon />
            </a>
            <span aria-hidden="true">surf {heightUnit(units)}</span>
            <span aria-hidden="true">swell</span>
            <span aria-hidden="true">wind kt</span>
            <span class="pp-head" aria-hidden="true">
              kJ<small>hPa</small>
            </span>
          </div>
          {hourRows}
          {dayHours.length === 0 && (
            <p class="state">Beyond the model horizon - no hourly detail yet.</p>
          )}

          <TideSection
            hours={data.hours}
            date={day.date}
            nowT={day.date === today ? cur.t : null}
            metric={units.height === "m"}
            tideBest={data.spot.tide_best}
          />

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, units, liveDay, id]);

  // Top bar: back arrow · spot switcher (masked, fills the middle) · fav star.
  const topBar = (
    <div class="spot-top">
      <button class="spot-back" onClick={goBack} aria-label="Back">
        <ChevronLeftIcon />
      </button>
      {switcherSpots.length > 1 && <SpotSwitcher spots={switcherSpots} currentId={id} />}
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
  const today = todayIn(data.spot.timezone);

  return (
    <main class="page">
      <div class={`spot-sticky${condensed ? " condensed" : ""}`}>
        {topBar}
        <DayScrubber
          data={data}
          days={days}
          selected={daySelClamped}
          live={liveClamped}
          today={today}
          onSelect={commitDay}
          onScrub={setLiveDay}
        />
      </div>
      {panel}
    </main>
  );
}
