import { useEffect, useRef, useState } from "preact/hooks";
import { fetchIndex } from "../api";
import { tierOf } from "../conditions";
import { getPosition } from "../geo";
import { RatingChip } from "../components/parts";
import { fmtRange, useUnits } from "../units";
import type { Bucket, SpotIndex } from "../types";
import type { Theme } from "../theme";

type Entry = [string, SpotIndex["spots"][string]];

// CARTO raster basemaps (free tier, attribution required) — swap to self-hosted
// vector tiles before public launch.
const TILE_URLS: Record<Theme, string> = {
  dark: "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
  light: "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
};
const ATTRIBUTION = "© OpenStreetMap contributors © CARTO";

/** Tier colors come from the theme tokens — no hexes here. */
function condColor(bucket: Bucket): string {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(`--cond-${tierOf(bucket)}`)
    .trim();
}

interface MapHandle {
  easeTo(opts: { center: [number, number]; duration?: number }): void;
  remove(): void;
}

/** maplibre-gl is ~70 KB gz — loaded only when the Map tab opens. */
export function MapPage({ theme }: { theme: Theme }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapHandle | null>(null);
  const dotsRef = useRef<HTMLElement[]>([]);
  const scrollTimer = useRef<number | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [spots, setSpots] = useState<Entry[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const units = useUnits();

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

        // north → south, the drawer's swipe order
        const ordered = Object.entries(index.spots).sort(([, a], [, b]) => b.lat - a.lat);
        setSpots(ordered);

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
          center: pos ? [pos.lon, pos.lat] : [34.8, 32.3],
          zoom: pos ? 9 : 7,
          attributionControl: { compact: true },
        });
        map = m as unknown as MapHandle;
        mapRef.current = map;

        m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
        m.on("click", () => setOpen(null));

        dotsRef.current = ordered.map(([, e], i) => {
          const dot = document.createElement("div");
          dot.className = "spot-dot";
          dot.style.background = condColor(e.bucket);
          dot.addEventListener("click", (ev) => {
            ev.stopPropagation();
            setOpen(i);
          });
          new maplibregl.Marker({ element: dot }).setLngLat([e.lon, e.lat]).addTo(m);
          return dot;
        });

        if (pos) {
          const you = document.createElement("div");
          you.className = "you-dot";
          new maplibregl.Marker({ element: you }).setLngLat([pos.lon, pos.lat]).addTo(m);
        } else {
          const lons = ordered.map(([, e]) => e.lon);
          const lats = ordered.map(([, e]) => e.lat);
          m.fitBounds(
            [
              [Math.min(...lons), Math.min(...lats)],
              [Math.max(...lons), Math.max(...lats)],
            ],
            { padding: 56, maxZoom: 9 }
          );
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

  // marker tap → scroll drawer to that card; highlight + center follow
  useEffect(() => {
    dotsRef.current.forEach((d, i) => d.classList.toggle("active", i === open));
    if (open === null) return;
    const entry = spots[open];
    if (entry) mapRef.current?.easeTo({ center: [entry[1].lon, entry[1].lat], duration: 400 });
    const track = trackRef.current;
    if (track) track.scrollTo({ left: open * track.clientWidth, behavior: "instant" as ScrollBehavior });
  }, [open === null ? null : open, spots.length]);

  // swipe between adjacent spots: settle detection on the snap container
  const onTrackScroll = () => {
    const track = trackRef.current;
    if (!track) return;
    clearTimeout(scrollTimer.current);
    scrollTimer.current = window.setTimeout(() => {
      const idx = Math.round(track.scrollLeft / track.clientWidth);
      if (idx !== open && idx >= 0 && idx < spots.length) {
        setOpen(idx);
      }
    }, 90);
  };

  if (error) return <main class="page"><p class="state">{error}</p></main>;
  return (
    <>
      <div class="map-wrap" aria-label="Spot map">
        {/* inner div is maplibre's — its stylesheet overrides position on the container */}
        <div class="map-canvas" ref={wrapRef} />
      </div>
      {open !== null && spots.length > 0 && (
        <div class="drawer" aria-label="Spot preview">
          <button class="drawer-close" onClick={() => setOpen(null)} aria-label="Close preview">
            ×
          </button>
          <div class="drawer-track" ref={trackRef} onScroll={onTrackScroll}>
            {spots.map(([id, e]) => (
              <a class="drawer-card" href={`#/spot/${id}`} key={id}>
                <span class="drawer-name">{e.name}</span>
                <span class="drawer-meta">
                  <RatingChip bucket={e.bucket} />
                  <b>{fmtRange(e.h, units)}</b>
                </span>
                <span class="drawer-hint">open forecast →</span>
              </a>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
