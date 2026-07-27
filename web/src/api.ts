import type { SpotIndex, SpotPayload } from "./types";

// Base origin for published forecast JSON. Empty (default) → same-origin
// `/data/...`, which is what local dev serves via sync-data. In production the
// pipeline publishes to a separate Vercel data project; set VITE_DATA_BASE to
// that origin (e.g. https://rosa-data.vercel.app) at build time.
const DATA_BASE = import.meta.env.VITE_DATA_BASE ?? "";

export async function fetchSpot(id: string): Promise<SpotPayload> {
  const res = await fetch(`${DATA_BASE}/data/spots/${encodeURIComponent(id)}.json`);
  if (!res.ok) throw new Error(`Forecast for "${id}" isn't published yet.`);
  return (await res.json()) as SpotPayload;
}

export async function fetchIndex(): Promise<SpotIndex> {
  const res = await fetch(`${DATA_BASE}/data/index.json`);
  if (!res.ok) throw new Error("The spot list isn't published yet.");
  return (await res.json()) as SpotIndex;
}

/* ---- SwellMap basin layer (animated wave fields, precomputed by the pipeline) ---- */

export interface SwellFrame {
  t: string;
  hs: number[]; // u8 * hs_m metres; 255 = land/missing
  per: number[];
  dir: number[];
  wind?: number[]; // u8 * wind_ms m/s - absent in pre-wind payloads
  wdir?: number[];
}

export interface SwellBasin {
  basin: string;
  regions: string[];
  model: string;
  run: string;
  attribution: string;
  scales: { hs_m: number; per_s: number; dir_deg: number; wind_ms?: number; missing: number };
  ny: number;
  nx: number;
  lat_first: number;
  lat_last: number;
  lon_first: number;
  lon_last: number;
  frames: SwellFrame[];
}

export type SwellIndex = Record<
  string,
  { regions: string[]; run: string; frames: number; bbox: [number, number, number, number] }
>;

export async function fetchSwellIndex(): Promise<SwellIndex> {
  const res = await fetch(`${DATA_BASE}/data/swellmap/index.json`);
  if (!res.ok) throw new Error(`Swell layer isn't published yet. (${res.status})`);
  return (await res.json()) as SwellIndex;
}

export async function fetchSwellBasin(name: string): Promise<SwellBasin> {
  const res = await fetch(`${DATA_BASE}/data/swellmap/${encodeURIComponent(name)}.json`);
  if (!res.ok) throw new Error(`Swell frames for "${name}" aren't published yet.`);
  return (await res.json()) as SwellBasin;
}

/* ---- World layer: whole-globe frames, one stacked-grayscale PNG per timestep ---- */

export interface WorldMeta {
  model: string;
  grid_deg: number;
  run: string;
  attribution: string;
  scales: { hs_m: number; per_s: number; dir_deg: number; wind_ms: number; missing: number };
  planes: string[]; // vertical plane order inside each PNG: hs, per, dir, wind, wdir
  max: { hs: number; per: number; wind: number; energy: number };
  ny: number;
  nx: number;
  lat_first: number;
  lat_last: number;
  lon_first: number; // 0-360 grid - the renderer handles the wrap
  lon_last: number;
  frames: { t: string; png: string }[];
}

export async function fetchWorldMeta(): Promise<WorldMeta> {
  const res = await fetch(`${DATA_BASE}/data/swellmap/world.json`);
  if (!res.ok) throw new Error(`World layer isn't published yet. (${res.status})`);
  return (await res.json()) as WorldMeta;
}

/** URL of a file under /data/swellmap/ (world frame PNGs). */
export function swellmapAsset(path: string): string {
  return `${DATA_BASE}/data/swellmap/world/${path}`;
}
