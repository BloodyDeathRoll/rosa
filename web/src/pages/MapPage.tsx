import { useEffect, useRef, useState } from "preact/hooks";
import { fetchIndex } from "../api";
import { getPosition } from "../geo";
import { fmtRange, getUnits } from "../units";
import type { Theme } from "../theme";

const BUCKET_COLORS: Record<string, string> = {
  FLAT: "#6b7280",
  POOR: "#f5a524",
  FAIR: "#a8c63c",
  GOOD: "#2fc96c",
  FIRING: "#28d8e8",
};

// CARTO raster basemaps (free tier, attribution required) — matches the dark app.
// Swap to self-hosted vector tiles before public launch.
const TILE_URLS: Record<Theme, string> = {
  dark: "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
  light: "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
};
const ATTRIBUTION = "© OpenStreetMap contributors © CARTO";

/** maplibre-gl is ~70 KB gz — loaded only when the Map tab opens. */
export function MapPage({ theme }: { theme: Theme }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    let map: { remove(): void } | null = null;

    (async () => {
      try {
        const [{ default: maplibregl }, index, pos] = await Promise.all([
          import("maplibre-gl"),
          fetchIndex(),
          getPosition(),
        ]);
        await import("maplibre-gl/dist/maplibre-gl.css");
        if (disposed || !wrapRef.current) return;

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
        map = m;

        m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

        for (const [id, e] of Object.entries(index.spots)) {
          const dot = document.createElement("div");
          dot.className = "spot-dot";
          dot.style.background = BUCKET_COLORS[e.bucket] ?? BUCKET_COLORS.FLAT ?? "";
          const popup = new maplibregl.Popup({ offset: 14, closeButton: false }).setHTML(
            `<a class="map-popup" href="#/spot/${id}"><b>${e.name}</b><span>${e.bucket} · ${fmtRange(e.h, getUnits())}</span></a>`
          );
          new maplibregl.Marker({ element: dot }).setLngLat([e.lon, e.lat]).setPopup(popup).addTo(m);
        }

        if (pos) {
          const you = document.createElement("div");
          you.className = "you-dot";
          new maplibregl.Marker({ element: you }).setLngLat([pos.lon, pos.lat]).addTo(m);
        } else {
          const lons = Object.values(index.spots).map((e) => e.lon);
          const lats = Object.values(index.spots).map((e) => e.lat);
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
    };
  }, [theme]);

  if (error) return <main class="page"><p class="state">{error}</p></main>;
  return (
    <div class="map-wrap" aria-label="Spot map">
      {/* inner div is maplibre's — its stylesheet overrides position on the container */}
      <div class="map-canvas" ref={wrapRef} />
    </div>
  );
}
