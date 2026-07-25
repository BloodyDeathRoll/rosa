export interface LatLon {
  lat: number;
  lon: number;
}

let cached: Promise<LatLon | null> | null = null;

function request(maximumAge: number): Promise<LatLon | null> {
  return new Promise((resolve) => {
    if (!("geolocation" in navigator)) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
      () => resolve(null),
      { timeout: 8000, maximumAge }
    );
  });
}

/** One geolocation request per session; resolves null on denial/timeout/unsupported.
    NOTE: a failed fix caches null for the whole session - the map's locate button
    calls refreshPosition() to bust it. */
export function getPosition(): Promise<LatLon | null> {
  cached ??= request(5 * 60_000);
  return cached;
}

/** Force a fresh fix (no cache) and make it the new session answer. */
export function refreshPosition(): Promise<LatLon | null> {
  cached = request(0);
  return cached;
}

export function distanceKm(a: LatLon, b: LatLon): number {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(s));
}
