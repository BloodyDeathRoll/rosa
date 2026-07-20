import { useEffect, useRef, useState } from "preact/hooks";
import { fetchIndex, fetchSpot } from "../api";
import { AppHeader, Pill, SpotTitle } from "../components/parts";
import { SpotCard } from "../components/SpotCard";
import { ratingVar } from "../conditions";
import { dateOf, splitName } from "../format";
import { distanceKm, getPosition } from "../geo";
import type { IndexEntry, SpotPayload } from "../types";
import type { Theme } from "../theme";

type Entry = [string, IndexEntry];

// CARTO raster basemaps (free tier, attribution required) — swap to self-hosted
// vector tiles before public launch.
const TILE_URLS: Record<Theme, string> = {
  dark: "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
  light: "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
};
const ATTRIBUTION = "© OpenStreetMap contributors © CARTO";

/** "Show on map" hand-off from the spot screen: select this pin on next open. */
let pendingPin: string | null = null;
export function setPendingPin(id: string): void {
  pendingPin = id;
}

interface MapHandle {
  easeTo(opts: { center: [number, number]; duration?: number }): void;
  remove(): void;
}

/** maplibre-gl is ~70 KB gz — loaded only when the Map tab opens. */
export function MapPage({ theme }: { theme: Theme }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapHandle | null>(null);
  const dotsRef = useRef<Record<string, HTMLElement>>({});
  const [error, setError] = useState<string | null>(null);
  const [spots, setSpots] = useState<Entry[]>([]);
  const [pin, setPin] = useState<string | null>(null);
  const [payload, setPayload] = useState<SpotPayload | null>(null);

  useEffect(() => {
    let disposed = false;
    let map: MapHandle | null = null;

    (async () => {
      try {
        const [{ default: maplibregl }, index, pos] = await Promise.all([
          import("maplibre-gl"),
          fetchIndex(),
          getPosition(),
        ]);
        await import("maplibre-gl/dist/maplibre-gl.css");
        if (disposed || !wrapRef.current) return;

        const ordered = Object.entries(index.spots).sort(([, a], [, b]) => b.lat - a.lat);
        setSpots(ordered);

        // default pin: hand-off from a spot page > nearest to you > northernmost
        const nearest = pos
          ? [...ordered].sort(
              ([, a], [, b]) =>
                distanceKm(pos, { lat: a.lat, lon: a.lon }) - distanceKm(pos, { lat: b.lat, lon: b.lon })
            )[0]?.[0]
          : ordered[0]?.[0];
        const start = pendingPin && index.spots[pendingPin] ? pendingPin : (nearest ?? null);
        pendingPin = null;
        setPin(start);

        const startEntry = start ? index.spots[start] : undefined;
        const m = new maplibregl.Map({
          container: wrapRef.current,
          style: {
            version: 8,
            sources: {
              carto: {
                type: "raster",
                tiles: [TILE_URLS[theme]],
                tileSize: 256,
                attribution: ATTRIBUTION,
              },
            },
            layers: [{ id: "carto", type: "raster", source: "carto" }],
          },
          center: startEntry
            ? [startEntry.lon, startEntry.lat]
            : pos
              ? [pos.lon, pos.lat]
              : [34.8, 32.3],
          zoom: 9,
          attributionControl: { compact: true },
        });
        map = m as unknown as MapHandle;
        mapRef.current = map;

        m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

        dotsRef.current = {};
        for (const [sid, e] of ordered) {
          const dot = document.createElement("div");
          dot.className = "spot-dot";
          dot.style.background = ratingVar(e.bucket);
          dot.addEventListener("click", (ev) => {
            ev.stopPropagation();
            setPin(sid);
          });
          new maplibregl.Marker({ element: dot }).setLngLat([e.lon, e.lat]).addTo(m);
          dotsRef.current[sid] = dot;
        }

        if (pos) {
          const you = document.createElement("div");
          you.className = "you-dot";
          new maplibregl.Marker({ element: you }).setLngLat([pos.lon, pos.lat]).addTo(m);
        }
      } catch {
        if (!disposed) setError("The map couldn't load. Check your connection and retry.");
      }
    })();

    return () => {
      disposed = true;
      map?.remove();
      mapRef.current = null;
    };
  }, [theme]);

  // selected pin: ring + center + fetch its forecast for the sheet
  useEffect(() => {
    for (const [sid, dot] of Object.entries(dotsRef.current))
      dot.classList.toggle("active", sid === pin);
    if (!pin) return;
    const entry = spots.find(([sid]) => sid === pin);
    if (entry) mapRef.current?.easeTo({ center: [entry[1].lon, entry[1].lat], duration: 400 });
    setPayload(null);
    let disposed = false;
    fetchSpot(pin).then(
      (p) => {
        if (!disposed) setPayload(p);
      },
      () => undefined
    );
    return () => {
      disposed = true;
    };
  }, [pin, spots]);

  if (error) {
    return (
      <main class="page">
        <AppHeader right={<span class="head-note">Israel</span>} />
        <p class="state">{error}</p>
      </main>
    );
  }

  const entry = spots.find(([sid]) => sid === pin)?.[1];
  const today = payload
    ? dateOf(payload.hours[0]?.t ?? payload.days[0]?.date ?? "")
    : "";

  return (
    <main class="page">
      <AppHeader right={<span class="head-note">Israel</span>} />
      <div class="map-page">
        <div class="map-canvas" ref={wrapRef} />
        {entry && pin && (
          <div class="map-sheet" aria-label="Spot preview">
            {payload ? (
              <SpotCard data={payload} date={today} />
            ) : (
              <MapSheetSkeleton entry={entry} />
            )}
          </div>
        )}
      </div>
    </main>
  );
}

/** Minimal card shown while the pinned spot's payload is loading — same shape
    as SpotCard so the sheet doesn't reflow when the data arrives. */
function MapSheetSkeleton({ entry }: { entry: IndexEntry }) {
  const { name, region } = splitName(entry.name);
  return (
    <div class="rank-card map-skel">
      <div class="mid">
        <div class="title-row">
          <SpotTitle name={name} region={region} />
        </div>
        <span class="line tabular">Loading…</span>
      </div>
      <div class="side">
        <Pill bucket={entry.bucket} />
      </div>
    </div>
  );
}
