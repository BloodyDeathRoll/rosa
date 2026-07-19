import { useEffect, useRef, useState } from "preact/hooks";
import { fetchIndex } from "../api";
import { getPosition } from "../geo";

const BUCKET_COLORS: Record<string, string> = {
  FLAT: "#6b7280",
  POOR: "#f5a524",
  FAIR: "#a8c63c",
  GOOD: "#2fc96c",
  FIRING: "#28d8e8",
};

/** maplibre-gl is ~70 KB gz — loaded only when the Map tab opens. */
export function MapPage() {
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
              osm: {
                type: "raster",
                tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
                tileSize: 256,
                attribution: "© OpenStreetMap contributors",
              },
            },
            layers: [{ id: "osm", type: "raster", source: "osm" }],
          },
          center: pos ? [pos.lon, pos.lat] : [34.8, 32.3],
          zoom: pos ? 9 : 7,
          attributionControl: { compact: true },
        });
        map = m;

        m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

        for (const [id, e] of Object.entries(index.spots)) {
          const popup = new maplibregl.Popup({ offset: 24, closeButton: false }).setHTML(
            `<a class="map-popup" href="#/spot/${id}"><b>${e.name}</b><span>${e.bucket} ${e.rating}</span></a>`
          );
          new maplibregl.Marker({ color: BUCKET_COLORS[e.bucket] ?? "#6b7280" })
            .setLngLat([e.lon, e.lat])
            .setPopup(popup)
            .addTo(m);
        }

        if (pos) {
          const dot = document.createElement("div");
          dot.className = "you-dot";
          new maplibregl.Marker({ element: dot }).setLngLat([pos.lon, pos.lat]).addTo(m);
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
  }, []);

  if (error) return <main class="page"><p class="state">{error}</p></main>;
  return (
    <div class="map-wrap" aria-label="Spot map">
      {/* inner div is maplibre's — its stylesheet overrides position on the container */}
      <div class="map-canvas" ref={wrapRef} />
    </div>
  );
}
