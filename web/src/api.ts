import type { SpotIndex, SpotPayload } from "./types";

export async function fetchSpot(id: string): Promise<SpotPayload> {
  const res = await fetch(`/data/spots/${encodeURIComponent(id)}.json`);
  if (!res.ok) throw new Error(`Forecast for "${id}" isn't published yet.`);
  return (await res.json()) as SpotPayload;
}

export async function fetchIndex(): Promise<SpotIndex> {
  const res = await fetch("/data/index.json");
  if (!res.ok) throw new Error("The spot list isn't published yet.");
  return (await res.json()) as SpotIndex;
}
