/** Regions (countries/areas) derived from the published index. A region is any
    distinct `region` value across the spots; its bounds are the lon/lat extent of
    the spots in it, used to frame the map when a search opens the area. */

import type { IndexEntry } from "./types";

/** [[west, south], [east, north]] — a maplibre LngLatBoundsLike. */
export type Bounds = [[number, number], [number, number]];

export interface RegionInfo {
  name: string;
  count: number;
  bounds: Bounds;
}

export function regionsFrom(spots: Record<string, IndexEntry>): RegionInfo[] {
  const acc = new Map<
    string,
    { count: number; minLat: number; maxLat: number; minLon: number; maxLon: number }
  >();
  for (const e of Object.values(spots)) {
    const name = e.region?.trim();
    if (!name) continue;
    const cur = acc.get(name);
    if (!cur) {
      acc.set(name, { count: 1, minLat: e.lat, maxLat: e.lat, minLon: e.lon, maxLon: e.lon });
    } else {
      cur.count++;
      cur.minLat = Math.min(cur.minLat, e.lat);
      cur.maxLat = Math.max(cur.maxLat, e.lat);
      cur.minLon = Math.min(cur.minLon, e.lon);
      cur.maxLon = Math.max(cur.maxLon, e.lon);
    }
  }
  return [...acc.entries()]
    .map(([name, v]) => ({
      name,
      count: v.count,
      bounds: [
        [v.minLon, v.minLat],
        [v.maxLon, v.maxLat],
      ] as Bounds,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function findRegion(
  spots: Record<string, IndexEntry>,
  name: string
): RegionInfo | undefined {
  const q = name.toLowerCase();
  return regionsFrom(spots).find((r) => r.name.toLowerCase() === q);
}

export function boundsCenter(b: Bounds): [number, number] {
  return [(b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2];
}
