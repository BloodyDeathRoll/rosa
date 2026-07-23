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
