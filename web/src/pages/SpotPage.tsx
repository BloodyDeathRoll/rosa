import type { VNode } from "preact";
import { navigate, onRouteChange } from "../router";
import { setHead, spotHead } from "../head";
import { useCallback, useEffect, useMemo, useState } from "preact/hooks";
import { fetchIndex, fetchSpot } from "../api";
import { gaEvent } from "../ga";
import {
  ChevronLeftIcon,
  FlagIcon,
  InfoIcon,
  MapIcon,
  SearchIcon,
  ShirtIcon,
  SwellDirIcon,
  ThermometerIcon,
  WavesIcon,
  WindDirIcon,
} from "../components/icons";
import { DayScrubber } from "../components/CoastChart";
import { ReportSheet } from "../components/ReportSheet";
import { Pill, ShareButton, StarButton, SwimPill } from "../components/parts";
import { ratingVar } from "../conditions";
import {
  bestSwim,
  CHOP_MAX,
  daySwim,
  daylightOf,
  GEAR_WORD,
  gearFor,
  peakPeriod,
  PUSH_OUT_MAX,
  PUSH_OUT_RED_KT,
  PUSH_WORD,
  pushOf,
  ripLevel,
  rockyEntry,
  shoreBreak,
  SURGE_HIGH,
  surgeLevel,
  SWIM_RAIL_FILL,
  swimNote,
  swimScore,
  swimVar,
  toKnots,
  type DaySwim,
  type Mode,
} from "../lib/swim";
import { useMode } from "../mode";
import { useFavorites } from "../favorites";
import { stashView } from "../feedback";
import { pushRecent } from "../recents";
import { onScroll as onAppScroll, scrollTop } from "../scroller";
import { signalReady } from "../splash";
import {
  arrowRotation,
  cardinal,
  dateOf,
  dayDate,
  dayLabel,
  hourOf,
  knots,
  nowIn,
  splitName,
  todayIn,
  windClassWord,
} from "../format";
import { distanceKm } from "../geo";
import { currentIds } from "../cams";
import { TideSection } from "../components/TideSection";
import { MapCard, setPendingPin } from "./MapPage";
import { fmtClock, sunTimes } from "../sun";
import { fmtH, fmtTemp, heightUnit, useUnits, type Units } from "../units";
import type { DayEntry, HourEntry, IndexEntry, SpotPayload } from "../types";

const NEARBY_KM = 50; // the app's nearby radius, same as the cam picker's
const NEARBY_MAX = 6;

/** How far the rating rail fills its track: one fifth per tier, so the column
    reads as a bar chart down the hours - flat is a red stub, epic runs full. */
const RAIL_FILL: Record<string, number> = {
  FLAT: 20,
  POOR: 40,
  FAIR: 60,
  GOOD: 80,
  FIRING: 100,
};

const railFill = (bucket: string): number => RAIL_FILL[bucket] ?? 20;

function qClass(q: number): string {
  return q >= 0.7 ? "q-good" : q >= 0.45 ? "q-fair" : q >= 0.25 ? "q-warn" : "q-poor";
}

const pmOf = (hours: HourEntry[]) =>
  hours.filter((h) => {
    const H = Number(h.t.slice(11, 13));
    return H >= 12 && H <= 18;
  });

// Clarity bar scale: Secchi depth at which the track is full. A display scale, not a
// tuning knob (docs/UI.md): 15 m is gin-clear ocean water, ~3 m is an estuary plume.
const CLARITY_FULL_M = 15;

type BarRow = { l: string; q: number | null; tag?: string; alert?: boolean };

/** Size / Period / Wind for the selected day, then Clarity / Pollution for the spot
    (measured, not forecast - same on every day, like air/water). null q = "no data". */
function DayBars({
  day,
  hours,
  water,
}: {
  day: DayEntry;
  hours: HourEntry[];
  water: SpotPayload["water"];
}) {
  // PEAK period, matching every other swell readout (see CLAUDE.md §UI "display != scoring").
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
    // Ramp, not a bare divisor: peak periods below ~5 s barely occur, so scaling from zero
    // wasted the bottom third of the track. 5 s empty -> 15 s full spans p5..p91 of the
    // fleet's day-max in-window peak period, and lands the qClass tiers where a surfer
    // would put them (6 s windswell poor, 10 s fair, 12 s+ good). The old /9 read FULL on
    // 58% of days - it was set for MEAN periods and never rescaled when the readouts moved
    // to peak (CLAUDE.md §UI "display != scoring").
    { l: "Period", q: Math.max(0, Math.min(1, (per - 5) / 10)) },
    { l: "Wind", q: hours.length > 0 ? Math.max(0.12, 1 - pmKts / 22) : 0 },
  ];
  const clarity = water?.clarity ?? null;
  const pollution = water?.pollution ?? null;
  const rows: BarRow[] = [
    ...bars,
    clarity
      ? { l: "Clarity", q: Math.min(1, clarity.zsd_m / CLARITY_FULL_M), tag: "daily" }
      : { l: "Clarity", q: null },
    pollution
      ? {
          l: "Pollution",
          q: pollution.grade / 4,
          tag: pollution.cadence === "yearly" ? "yearly" : "daily",
          alert: pollution.alert,
        }
      : { l: "Pollution", q: null },
  ];
  return (
    <div class="why-bars">
      {rows.map((b) => (
        <div class="bar" key={b.l}>
          <span>{b.l}</span>
          {b.q === null ? (
            <span class="bar-nodata">no data</span>
          ) : (
            <span class="track">
              <i
                class={b.alert ? "q-poor" : qClass(b.q)}
                style={`width:${Math.round(b.q * 100)}%`}
              />
            </span>
          )}
          {/* every row reserves the tag column so all five tracks end at one line */}
          <span class="bar-tag">{b.tag ?? ""}</span>
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


/** Live cam block, first thing on the page when a spot has one.
 *
 * Embedded through YouTube's own iframe player - the only way a cam is allowed into Rosa
 * (CLAUDE.md: never scrape a stream, never touch a competitor's). The credit under the
 * frame is the acknowledgement that permission implies, and it links back to the channel.
 * `loading="lazy"` keeps the player off the wire until it scrolls in, so the sub-2 s first
 * load target survives; nothing here blocks the forecast rendering.
 *
 * Surfline-style picker under the player: Angles = this spot's cameras, Nearby =
 * cameras at other spots within 50 km (the app's nearby radius), closest first.
 * Thumbnails are YouTube's own stills; an angle swaps the player in place, a
 * nearby pick opens that spot's page - the stream belongs with its forecast. */
function CamSection({ data, all }: { data: SpotPayload; all: [string, IndexEntry][] }) {
  const spot = data.spot;
  const cams = spot.cams ?? (spot.cam ? [spot.cam] : []);
  const [tab, setTab] = useState<"angles" | "nearby">("angles");
  const [sel, setSel] = useState(0);
  // what each angle plays now - the committed ids rot on every stream restart (cams.ts);
  // null until the channel feeds answer, so a dead id never loads first
  const [ids, setIds] = useState<string[] | null>(null);

  useEffect(() => {
    setTab("angles");
    setSel(0);
  }, [spot.id]);

  useEffect(() => {
    let live = true;
    setIds(null);
    void currentIds(cams).then((v) => live && setIds(v));
    return () => {
      live = false;
    };
  }, [spot.id]);

  if (!cams.length) return null;

  const nearby = all
    .filter(([id, e]) => id !== spot.id && (e.cams?.length ?? (e.cam ? 1 : 0)) > 0)
    .map(([id, e]) => ({ id, name: e.name, km: distanceKm(spot, e), yts: e.cams ?? [e.cam!] }))
    .filter((n) => n.km <= 50)
    .sort((a, b) => a.km - b.km);

  const idx = Math.min(sel, cams.length - 1);
  const active = cams[idx]!;
  const playing = ids?.[idx];
  const thumb = (yt: string) => `https://i.ytimg.com/vi/${yt}/mqdefault.jpg`;

  return (
    <section class="cam">
      <div class="cam-frame">
        {playing && (
          <iframe
            // autoplay muted is what strips the embed back to the play bar: the title
            // bar, channel avatar, big play button and "Watch on YouTube" overlay all
            // belong to the unstarted state and have no parameter to turn them off.
            // Muted is also the only autoplay mobile browsers allow.
            key={playing}
            src={
              `https://www.youtube-nocookie.com/embed/${playing}` +
              `?rel=0&playsinline=1&autoplay=1&mute=1&modestbranding=1&iv_load_policy=3`
            }
            title="Live cam"
            loading="lazy"
            allow="autoplay; accelerometer; encrypted-media; gyroscope; picture-in-picture; fullscreen"
            allowFullScreen
            frameBorder="0"
          />
        )}
      </div>
      <p class="cam-credit">
        Live cam by{" "}
        <a href={active.by_url} target="_blank" rel="noopener noreferrer">
          {active.by}
        </a>{" "}
        on YouTube
        {active.note ? ` - ${active.note}` : ""}
      </p>
      {(cams.length > 1 || nearby.length > 0) && (
        <div class="cam-picker">
          <div class="cam-tabs" role="tablist" aria-label="Cameras">
            <button
              role="tab"
              aria-selected={tab === "angles"}
              class={`group-chip${tab === "angles" ? " on" : ""}`}
              onClick={() => setTab("angles")}
            >
              Angles
            </button>
            {nearby.length > 0 && (
              <button
                role="tab"
                aria-selected={tab === "nearby"}
                class={`group-chip${tab === "nearby" ? " on" : ""}`}
                onClick={() => setTab("nearby")}
              >
                Nearby
              </button>
            )}
          </div>
          <div class="cam-thumbs">
            {tab === "angles"
              ? cams.map((c, i) => (
                  <button
                    key={c.yt}
                    class={`cam-thumb${sel === i ? " on" : ""}`}
                    onClick={() => setSel(i)}
                  >
                    <img src={thumb(ids?.[i] ?? c.yt)} alt="" loading="lazy" />
                    <span>{c.label ?? `Angle ${i + 1}`}</span>
                  </button>
                ))
              : nearby.map((n) => (
                  // one thumb per spot (its angles live on its page) - a tap opens
                  // the whole spot, forecast and all, not just the stream
                  <button
                    key={n.id}
                    class="cam-thumb"
                    onClick={() => (navigate(`/spot/${n.id}`))}
                  >
                    <img src={thumb(n.yts[0]!)} alt="" loading="lazy" />
                    <span>
                      {splitName(n.name).name} · {Math.round(n.km)} km
                    </span>
                  </button>
                ))}
          </div>
        </div>
      )}
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
      <span class="bar">
        <i style={`height:${railFill(h.bucket)}%;background:${ratingVar(h.bucket)}`} />
      </span>
      <span class="surf">
        <b class="tabular">
          {fmtH(h.h[0], units)}-{fmtH(h.h[1], units)}
        </b>
        {/* Offshore significant height of the same swell the next column names -
            the deep-water wave that becomes the breaking range above it. It sits
            here in place of the range's midpoint, which the range already told
            you. Carries its unit so it can't be read as a second surf figure. */}
        <small class="tabular">
          {swell ? `${fmtH(swell.h, units)} ${heightUnit(units)}` : "-"}
        </small>
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

/** The forecast for one day of one spot: cam, rating card, hourly table, tide, sun.
    Pure - everything it shows comes in through props, so the surf-mode output can be
    rendered to a string and compared byte for byte (src/test). */
export function SpotPanel({
  data,
  dayIndex,
  today,
  units,
  spots,
  id,
  onReport,
  mode = "surf",
}: {
  data: SpotPayload;
  dayIndex: number;
  /** the spot's current date (YYYY-MM-DD, spot-local) */
  today: string;
  units: Units;
  spots: [string, IndexEntry][];
  id: string;
  onReport: () => void;
  /** surf (default) renders exactly what it always has; swim re-reads the same data */
  mode?: Mode;
}) {
    // swim mode only: kJ / hPa shown under the rip column (the header's expand)
    const [power, setPower] = useState(false);
    const swim = mode === "swim";
    const days = data.days;
    const cur = data.current;
    const i = Math.min(Math.max(dayIndex, 0), days.length - 1);
    const day = days[i];
    if (!day) return null;
    const dayHours = data.hours.filter((h) => dateOf(h.t) === day.date);
      const sun = sunTimes(new Date(`${day.date}T12:00:00Z`), data.spot.lat, data.spot.lon);
      // daylight bounds in spot-local minutes so pre-dawn/post-dusk slots are excluded
      const toMin = (d: Date) => {
        const [hh, mm] = fmtClock(d, data.spot.timezone).split(":");
        return Number(hh) * 60 + Number(mm);
      };
      const daylight = swim ? daylightOf(data.spot, day.date) : null;
      const chips = daylight
        ? bestSwim(dayHours, data.hours, data.water, daylight)
        : sessionChips(dayHours, toMin(sun.firstLight), toMin(sun.lastLight));
      const dsw = daylight ? daySwim(dayHours, data.water, daylight) : null;
      const rocky = swim && rockyEntry(data.spot.shore);
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
          swim ? (
            <SwimHourRow
              key={h.t}
              h={h}
              water={data.water}
              units={units}
              power={power}
              best={isBest}
              first={isBest && !prevBest}
              last={isBest && !nextBest}
              label={isBest && !prevBest ? "Best swim" : undefined}
            />
          ) : (
            <HourRow
              key={h.t}
              h={h}
              units={units}
              best={isBest}
              first={isBest && !prevBest}
              last={isBest && !nextBest}
              label={isBest && !prevBest ? "Best session" : undefined}
            />
          )
        );
      }
      return (
        <div class="spot-main">
          <CamSection data={data} all={spots} />
          {rocky && (
            <p class="swim-banner" role="note">
              Rocky entry - not a swimming beach
            </p>
          )}
          {dsw ? (
            <section class="spot-card swim-card">
              <div class="rc-left">
                <div class="rc-head">
                  {!rocky && <SwimPill bucket={dsw.bucket} />}
                  <button
                    class="accent-link"
                    onClick={() => {
                      setPendingPin(id);
                      navigate("/map");
                    }}
                  >
                    <MapIcon size={14} />
                    Map
                  </button>
                </div>
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
                  {gearFor(cur.sst) && (
                    <span>
                      <ShirtIcon />
                      <span class="suit">{GEAR_WORD[gearFor(cur.sst)!]}</span>
                    </span>
                  )}
                </div>
              </div>
              <div class="rc-right">
                <SwimDayBars day={dsw} water={data.water} />
              </div>
            </section>
          ) : (
          <section class="spot-card">
            <div class="rc-left">
              <div class="rc-head">
                <Pill bucket={day.bucket} />
                <button
                  class="accent-link"
                  onClick={() => {
                    setPendingPin(id);
                    navigate("/map");
                  }}
                >
                  <MapIcon size={14} />
                  Map
                </button>
              </div>
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
            <div class="rc-right">
              <DayBars day={day} hours={dayHours} water={data.water} />
            </div>
          </section>
          )}

          {/* one box around the day's table, so the wide layout can seat it
              beside the rating/tide column (styles.css DESKTOP) */}
          <div class="spot-hours">
          <div class="day-title">
            <div class="day-title-text">
              <b>
                {dayLabel(day.date, today)} · {dayDate(day.date)}
              </b>
              <span>{swim ? swimNote(dayHours, data.water) : dayNote(days, i, dayHours)}</span>
            </div>
            {/* Reports are read by a human before anything changes - see ReportSheet. */}
            <button
              class="report-cta"
              onClick={onReport}
              aria-label={`Report an issue with ${data.spot.name}`}
            >
              <FlagIcon />
              Report
            </button>
          </div>
          {swim ? (
            <div class="hour-grid head">
              <span aria-hidden="true" />
              <span aria-hidden="true" />
              <a class="head-info" href="/about/reading#swim" aria-label="What shore break means">
                <span aria-hidden="true">shore break {units.height === "ft" ? "in" : "cm"}</span>
                <InfoIcon size={12} />
              </a>
              <a class="head-info" href="/about/reading#swim" aria-label="What surge means">
                <span aria-hidden="true">surge</span>
                <InfoIcon size={12} />
              </a>
              <a class="head-info" href="/about/reading#swim" aria-label="What push in and push out mean">
                <span aria-hidden="true">wind kt</span>
                <InfoIcon size={12} />
              </a>
              {/* the expand: kJ and hPa live under the rip chip while this is on */}
              <button
                class={`head-info${power ? " on" : ""}`}
                aria-expanded={power}
                aria-label={power ? "Hide wave energy and pressure" : "Show wave energy and pressure"}
                onClick={() => setPower((p) => !p)}
              >
                <span class="pp-head" aria-hidden="true">
                  rip<small>water</small>
                </span>
                <InfoIcon size={12} />
              </button>
            </div>
          ) : (
          <div class="hour-grid head">
            <span aria-hidden="true" />
            <span aria-hidden="true" />
            {/* Each column's way out to its own section of the glossary
                (AboutPage scrolls to the #id). 12px: 18 (the share's) read too large. */}
            <a class="head-info" href="/about/reading#surf" aria-label="What the surf numbers mean">
              <span aria-hidden="true">surf {heightUnit(units)}</span>
              <InfoIcon size={12} />
            </a>
            <a class="head-info" href="/about/reading#swell" aria-label="What the swell numbers mean">
              <span aria-hidden="true">swell</span>
              <InfoIcon size={12} />
            </a>
            <a class="head-info" href="/about/reading#wind" aria-label="What the wind numbers mean">
              <span aria-hidden="true">wind kt</span>
              <InfoIcon size={12} />
            </a>
            <a class="head-info" href="/about/reading#kj" aria-label="What kJ and hPa mean">
              <span class="pp-head" aria-hidden="true">
                kJ<small>hPa</small>
              </span>
              <InfoIcon size={12} />
            </a>
          </div>
          )}
          {hourRows}
          {dayHours.length === 0 && (
            <p class="state">Beyond the model horizon - no hourly detail yet.</p>
          )}
          </div>

          <TideSection
            hours={data.hours}
            date={day.date}
            // live wall clock in the spot's tz - NOT cur.t, which is the hour the
            // pipeline considered current at generation time (hours stale between runs)
            nowT={day.date === today ? nowIn(data.spot.timezone) : null}
            metric={units.height === "m"}
            tideBest={data.spot.tide_best}
            mode={mode}
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
}

/** Swim mode's five bars: Clarity / Pollution for the spot (measured), then the
    selected day's worst Chop / Surge / Push. Same markup as DayBars, so the two
    modes' cards sit identically. */
function SwimDayBars({ day, water }: { day: DaySwim; water: SpotPayload["water"] }) {
  const clarity = water?.clarity ?? null;
  const pollution = water?.pollution ?? null;
  const rows: BarRow[] = [
    clarity
      ? { l: "Clarity", q: Math.min(1, clarity.zsd_m / CLARITY_FULL_M), tag: "daily" }
      : { l: "Clarity", q: null },
    pollution
      ? {
          l: "Pollution",
          q: pollution.grade / 4,
          tag: pollution.cadence === "yearly" ? "yearly" : "daily",
          alert: pollution.alert,
        }
      : { l: "Pollution", q: null },
    { l: "Chop", q: Math.max(0.12, 1 - day.worst.chop / CHOP_MAX) },
    { l: "Surge", q: Math.max(0.12, 1 - Math.min(1, day.worst.surge / SURGE_HIGH)) },
    { l: "Push", q: Math.max(0.12, 1 - day.worst.push / PUSH_OUT_MAX) },
  ];
  return (
    <div class="why-bars">
      {rows.map((b) => (
        <div class="bar" key={b.l}>
          <span>{b.l}</span>
          {b.q === null ? (
            <span class="bar-nodata">no data</span>
          ) : (
            <span class="track">
              <i
                class={b.alert ? "q-poor" : qClass(b.q)}
                style={`width:${Math.round(b.q * 100)}%`}
              />
            </span>
          )}
          <span class="bar-tag">{b.tag ?? ""}</span>
        </div>
      ))}
    </div>
  );
}

/** One hour read for a swimmer: swim rail, shore break as one figure, surge, the
    wind as push in / out / drift (never the surfer's green-for-offshore), rip risk
    and water temperature. kJ and hPa sit behind the header's expand (`power`). */
function SwimHourRow({
  h,
  water,
  units,
  power,
  best,
  first,
  last,
  label,
}: {
  h: HourEntry;
  water: SpotPayload["water"];
  units: Units;
  power: boolean;
  best?: boolean;
  first?: boolean;
  last?: boolean;
  label?: string;
}) {
  const s = swimScore(h, water);
  const tp = peakPeriod(h);
  const surge = surgeLevel(h);
  const rip = ripLevel(h);
  const push = pushOf(h);
  const kts = toKnots(h.wind.kph);
  const brk = shoreBreak(h.h_mid, units.height === "ft");
  return (
    <div
      class={`hour-grid row swim-row${best ? " best" : ""}${first ? " best-first" : ""}${
        last ? " best-last" : ""
      }`}
    >
      {label && <span class="best-tag swim-tag">{label}</span>}
      <span class="t tabular">{hourOf(h.t)}</span>
      <span class="bar">
        <i style={`height:${SWIM_RAIL_FILL[s.bucket]}%;background:${swimVar(s.bucket)}`} />
      </span>
      <span class="surf">
        <b class="tabular">{brk.n}</b>
      </span>
      <span class="vec swell-cell">
        {tp !== null ? (
          <>
            <span class="top">
              <b class="tabular">{Math.round(tp)}s</b>
            </span>
            <small>
              sets · <em class={`lvl lvl-${surge}`}>{surge}</em>
            </small>
          </>
        ) : (
          <small>-</small>
        )}
      </span>
      <span
        class={`wind-cell push-${push}${push === "out" && kts >= PUSH_OUT_RED_KT ? " hard" : ""}`}
      >
        <span class="top">
          <WindDirIcon rotate={arrowRotation(h.wind.dir)} />
          <b class="tabular">{knots(h.wind.kph)}</b>
          <small class="cardinal tabular">{cardinal(h.wind.dir)}</small>
        </span>
        <small class="wclass">{PUSH_WORD[push]}</small>
      </span>
      <span class="pp swim-rip">
        <b
          class={`rip-chip rip-${rip}`}
          title="Rip risk - a heuristic from wave height and period, not a measurement"
        >
          {rip}
        </b>
        <small class="tabular">{h.sst !== null ? fmtTemp(h.sst, units) : "-"}</small>
        {power && (
          <small class="press tabular">
            {Math.round(h.energy_kj)} kJ · {h.pressure ?? "-"}
          </small>
        )}
      </span>
    </div>
  );
}

// Selected date carried across spot→spot navigation (the switcher chips keep
// SpotPage mounted, so this survives the id change). Cleared on unmount, so
// arriving fresh from Home/Map/Favorites still opens on today.
let stickyDate: string | null = null;

export function SpotPage({ id }: { id: string }) {
  const [data, setData] = useState<SpotPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [favs, toggleFav] = useFavorites();
  const [daySel, setDaySel] = useState(0);
  const [liveDay, setLiveDay] = useState(0);
  const [condensed, setCondensed] = useState(false);
  const [reporting, setReporting] = useState(false);
  const [spots, setSpots] = useState<[string, IndexEntry][]>([]);
  const units = useUnits();
  const mode = useMode();
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
        // The one event that answers "which spots do surfers in <country> open" -
        // the region rides along so the report groups without a spot dictionary.
        gaEvent("spot_view", {
          spot_id: d.spot.id,
          region: d.spot.region ?? "",
          bucket: data.days[0]?.bucket ?? "",
        });
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

  // A push notification's link (/spot/id?ev=YYYY-MM-DD) opens on the swell's
  // peak day. Reacts to route changes too: landing in an already-open app is a
  // navigation without a remount and must still jump the day.
  useEffect(() => {
    const apply = () => {
      const evDate = /[?&]ev=(\d{4}-\d{2}-\d{2})/.exec(location.search)?.[1];
      if (!evDate || !data) return;
      const i = data.days.findIndex((day) => day.date === evDate);
      if (i >= 0) commitDay(i);
    };
    apply();
    return onRouteChange(apply);
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
      const y = scrollTop();
      setCondensed((c) => (c ? y > 8 : y > 72));
    };
    onScroll();
    return onAppScroll(onScroll);
  }, []);

  useEffect(() => {
    // north→south ordering, same as the map drawer's swipe order
    fetchIndex().then(
      (idx) => setSpots(Object.entries(idx.spots).sort(([, a], [, b]) => b.lat - a.lat)),
      () => undefined
    );
  }, []);

  const goBack = () => {
    navigate("/");
  };

  // header falls back to the index entry's name while the payload loads
  const curEntry = spots.find(([sid]) => sid === id)?.[1];

  // <head> for this spot: from the payload once it is here, from the index
  // entry meanwhile (the prerendered shell already carries the same values)
  useEffect(() => {
    const sp = data?.spot ?? curEntry;
    if (!sp) return;
    // the full published name (an alias in brackets is what people search for)
    setHead(spotHead({ id, name: sp.name, region: sp.region ?? undefined, town: sp.town ?? undefined, lat: sp.lat, lon: sp.lon }));
  }, [data, curEntry, id]);

  // Other spots on this stretch of coast, closest first - the same cards the
  // Map tab uses, so a spot reads identically wherever you meet it.
  const nearby = curEntry
    ? spots
        .filter(([sid]) => sid !== id)
        .map(([sid, e]) => ({
          id: sid,
          entry: e,
          km: Math.round(distanceKm({ lat: curEntry.lat, lon: curEntry.lon }, e)),
        }))
        .filter(({ km }) => km <= NEARBY_KM)
        .sort((a, b) => a.km - b.km)
        .slice(0, NEARBY_MAX)
    : [];

  // the day scrubber drives the selected/live day; the panel below follows liveDay
  const allDays = data?.days ?? [];
  const daySelClamped = Math.min(daySel, Math.max(0, allDays.length - 1));
  const liveClamped = Math.min(liveDay, Math.max(0, allDays.length - 1));

  // The forecast for the live-scrubbed day. It rebuilds the instant the strip's
  // centered column changes (keyed on liveDay) - no second scroller and no
  // animation, so the data can't lag behind the date/bars or desync from them.
  const panel = useMemo(() => {
    if (!data) return null;
    return (
      <SpotPanel
        data={data}
        dayIndex={liveDay}
        today={todayIn(data.spot.timezone)}
        units={units}
        spots={spots}
        id={id}
        onReport={() => setReporting(true)}
        mode={mode}
      />
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, units, liveDay, id, spots, mode]);

  const spotName = splitName(data?.spot.name ?? curEntry?.name ?? "").name;

  // Header, one row: back arrow, spot name with its star right beside it, and
  // share and search pinned right - switching spots happens through search now.
  const topBar = (
    <div class="spot-top">
      <button class="spot-back" onClick={goBack} aria-label="Back">
        <ChevronLeftIcon />
      </button>
      <span class="spot-top-name">{spotName}</span>
      {data && (
        <StarButton
          on={favs.includes(id)}
          name={spotName}
          onToggle={() => toggleFav(id)}
        />
      )}
      <ShareButton
        class="icon-btn spot-top-share"
        path={`/spot/${id}`}
        title={`${spotName} surf forecast - Rosa`}
      />
      <a class="icon-btn spot-top-search" href="/search" aria-label="Search spots">
        <SearchIcon />
      </a>
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
          mode={mode}
        />
      </div>
      {panel}
      {reporting && data && (
        <ReportSheet
          spot={{
            id: data.spot.id,
            name: data.spot.name,
            town: data.spot.town,
            lat: data.spot.lat,
            lon: data.spot.lon,
          }}
          onClose={() => setReporting(false)}
          mode={mode}
        />
      )}
      {nearby.length > 0 && (
        <section class="nearby-sec">
          <span class="eyebrow">Other nearby spots:</span>
          <div class="map-cards nearby-cards">
            {nearby.map(({ id: nid, entry, km }) => (
              <MapCard key={nid} id={nid} entry={entry} dist={km} center={false} img />
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
