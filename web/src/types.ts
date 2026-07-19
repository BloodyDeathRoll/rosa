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
  energy: number; // deep-water wave energy flux, kW/m
  pressure: number | null; // mb
  wind: Wind;
  sst: number | null;
  swells: Swell[];
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

export interface SpotPayload {
  spot: { id: string; name: string; lat: number; lon: number; timezone: string };
  model: string;
  fetched_at: string;
  generated_at: string;
  attribution: string;
  current: CurrentEntry;
  hours: HourEntry[];
  days: DayEntry[];
}

export interface IndexEntry {
  name: string;
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
