/** Mirrors the pipeline's published JSON exactly (pipeline/src/rosa_pipeline/publish.py). */

export type Bucket = "FLAT" | "POOR" | "FAIR" | "GOOD" | "FIRING";
export type WindClass = "offshore" | "cross-shore" | "onshore";
export type Confidence = "high" | "medium" | "low";

export interface Swell {
  h: number;
  period: number;
  dir: number;
  kind: "swell" | "wind";
  in_window: boolean;
  spread?: number; // assumed directional spread, deg — modeled (see spectral_meta)
}

/** ECMWF spectral-lite (Stage 3b) — absent beyond the member's ~10-day horizon. */
export interface MissedSwell {
  t: [number, number]; // period band, s
  h: number; // unaccounted significant height, m
  energy: number; // kW/m
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
  energy: number; // deep-water wave energy, kJ per metre of crest (energy period Te)
  pressure: number | null; // mb
  air: number | null; // °C
  wind: Wind;
  sst: number | null;
  tide: number | null; // total water level vs MSL, m (null beyond the ~day-9 SMOC horizon)
  swells: Swell[];
  spectral?: SpectralHour;
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

export interface SpotPayload {
  spot: {
    id: string;
    name: string;
    region?: string;
    tide_best?: "low" | "mid" | "high" | null;
    lat: number;
    lon: number;
    timezone: string;
  };
  model: string;
  fetched_at: string;
  generated_at: string;
  attribution: string;
  spectral_meta?: { member: string | null; spread: string };
  current: CurrentEntry;
  hours: HourEntry[];
  days: DayEntry[];
  events?: SwellEventEntry[];
}

export interface IndexEntry {
  name: string;
  region?: string;
  lat: number;
  lon: number;
  rating: number;
  bucket: Bucket;
  h: [number, number];
  generated_at: string;
}

export interface SpotIndex {
  spots: Record<string, IndexEntry>;
}
