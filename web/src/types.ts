/** Mirrors the pipeline's published JSON exactly (pipeline/src/rosa_pipeline/publish.py). */

export type Bucket = "FLAT" | "POOR" | "FAIR" | "GOOD" | "FIRING";
export type WindClass = "offshore" | "cross-shore" | "onshore";
export type Confidence = "high" | "medium" | "low";

export interface Swell {
  h: number;
  period: number; // mean period, s - scoring uses this
  peak_period: number | null; // peak period Tp, s; null where the model publishes none
  dir: number;
  kind: "swell" | "wind";
  in_window: boolean;
  spread?: number; // assumed directional spread, deg - modeled (see spectral_meta)
}

/** ECMWF spectral-lite (Stage 3b) - absent beyond the member's ~10-day horizon. */
export interface MissedSwell {
  t: [number, number]; // period band, s
  h: number; // unaccounted significant height, m
  energy_kw: number; // deep-water energy FLUX of the band, kW per metre of crest
}

export interface SpectralHour {
  consistency?: number; // 0 lully … 100 setty
  missed?: MissedSwell[];
}

export interface Wind {
  kph: number;
  dir: number;
  class: WindClass;
}

export interface HourEntry {
  t: string; // ISO-8601 with spot-local offset
  rating: number;
  bucket: Bucket;
  h: [number, number];
  h_mid: number;
  phrase: string;
  energy_kj: number; // deep-water wave energy, kJ per metre of crest (energy period Te)
  pressure: number | null; // mb
  air: number | null; // °C
  wind: Wind;
  sst: number | null;
  tide: number | null; // total water level vs MSL, m (null beyond the ~day-9 SMOC horizon)
  swells: Swell[];
  spectral?: SpectralHour;
  // Stage 4 per-hour provenance of the breaker height's propagation link: "swan" when the
  // regional nearshore model carried the wave to the spot; absent on the shipping path
  // (the offshore point marched over the whole profile). Never a constant model label.
  nearshore?: "swan";
}

export interface CurrentEntry extends HourEntry {
  wetsuit: string | null;
  why: { size: number; period: number; wind: number };
}

export interface DayEntry {
  date: string;
  rating_max: number;
  bucket: Bucket;
  h_max: [number, number];
  confidence: Confidence;
}

export interface SwellEventEntry {
  start: string; // spot-local ISO
  peak: string;
  end: string;
  h_peak: number;
  dir: number | null;
  rating: number;
  bucket: Bucket;
}

export interface CamEntry {
  /** committed video id - the fallback; the player follows `ch` + `title` (cams.ts) */
  yt: string;
  by: string;
  by_url: string;
  /** the stream's channel id (UC...); absent in payloads published before 2026-09-15 */
  ch?: string;
  /** the stream's exact title - same title in the channel's feed = same camera */
  title?: string;
  note?: string;
  /** angle name when a spot has several cams ("Panorâmica 1") */
  label?: string;
}

export interface SpotPayload {
  spot: {
    id: string;
    name: string;
    region?: string;
    /** Nearest settlement - search matches it, nothing renders it as part of the name. */
    town?: string;
    tide_best?: "low" | "mid" | "high" | null;
    lat: number;
    lon: number;
    timezone: string;
    /** Embeddable live cam. Absent for almost every spot. `note` is set when the
        camera watches a beach near the spot rather than the peak itself. */
    cam?: CamEntry;
    /** Every angle when the spot has several cams; `cam` is always the first. */
    cams?: CamEntry[];
  };
  fetched_at: string;
  generated_at: string;
  attribution: string;
  /** Local-time stamp of the first published hour served by the GFS-Wave tail rather
      than best_match, or null when every visible hour is best_match. The payload is
      stitched per hour, so this boundary is the only true model label there is - a
      single constant name was wrong on ~40% of rows (retired 2026-08-14). Nothing
      renders it yet; it is provenance, never an input to a rating. */
  tail_from?: string | null;
  /** Blend arm only: when each wave model RAN (ISO UTC), per spot - `fetched_at` says
      only when Rosa asked, and Rosa may have dropped back one cycle (6-12 h) for this
      spot's box. Absent on the OM arm and on fixtures. Provenance, never an input. */
  model_run?: { gfswave: string; ecmwf: string | null };
  spectral_meta?: { member: string | null; spread: string };
  current: CurrentEntry;
  hours: HourEntry[];
  days: DayEntry[];
  events?: SwellEventEntry[];
}

export interface IndexEntry {
  name: string;
  region?: string;
  /** Nearest settlement, so "tel aviv" finds every Tel Aviv break. Search-only. */
  town?: string;
  lat: number;
  lon: number;
  rating: number;
  bucket: Bucket;
  h: [number, number];
  generated_at: string;
  /** YouTube id of this spot's live cam, when it has one - the map card shows its still. */
  cam?: string;
  /** Every angle's video id - the nearby-cams strip reads these without payload fetches. */
  cams?: string[];
}

export interface SpotIndex {
  spots: Record<string, IndexEntry>;
}
