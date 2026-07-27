import { useEffect, useRef, useState } from "preact/hooks";
import type { Map as MLMap } from "maplibre-gl";
import { fetchSwellBasin, fetchSwellIndex, type SwellBasin, type SwellIndex } from "../api";
import { signalReady } from "../splash";

/** Charts tab: animated basin wave fields (SwellMap v0.2), Surfline-style - a
    full-bleed map with a colormapped field, a chart-type selector, and a timeline.
    Deliberately separate from the Map tab, which is for finding spots.

    All three chart types render from the same published frames: height and peak
    period are stored; energy is derived here (P ~ 0.49 * H^2 * Te kW/m, Te = 0.9*Tp -
    the same convention as the hourly kJ column). Colour: single-hue sequential per
    variable, monotonic lightness, themed ramps - never a rainbow (dataviz method;
    also keeps us visually distinct from all-rights-reserved chart imagery). */

// CARTO raster basemaps - same source + attribution terms as the Map tab.
const TILE_URLS = {
  dark: "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
  light: "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
};
const ATTRIBUTION = "© OpenStreetMap contributors © CARTO";

type Variable = "hs" | "per" | "energy" | "wind";

const VARIABLES: { key: Variable; label: string; unit: string }[] = [
  { key: "hs", label: "Height", unit: "m" },
  { key: "per", label: "Period", unit: "s" },
  { key: "energy", label: "Energy", unit: "kW/m" },
  { key: "wind", label: "Wind", unit: "kt" },
];

// One hue per variable (teal / violet / amber), six steps, monotonic lightness.
// Both themes deepen with magnitude (light mode leads): pale = calm, deep = big,
// so the field reads the same either theme; dark just uses brighter endpoints.
const RAMPS: Record<Variable, { light: string[]; dark: string[] }> = {
  hs: {
    light: ["#dfeef4", "#b3d9e6", "#7cbcd2", "#4295b4", "#1d6f8c", "#0d4459"],
    dark: ["#a8e4f2", "#6cc3d8", "#3b9cb4", "#20758c", "#155163", "#0d3340"],
  },
  per: {
    light: ["#ece9f7", "#cdc5ee", "#a99add", "#8471c9", "#5e4aa8", "#3b2d75"],
    dark: ["#cfc7f2", "#a396dd", "#7b68cc", "#5443ab", "#3a2f7c", "#241d4e"],
  },
  energy: {
    light: ["#fdeedd", "#f8d3ab", "#f0b077", "#e08a4c", "#b96426", "#84440f"],
    dark: ["#f9cf9b", "#eda45c", "#cc7c30", "#9c5a1c", "#6b3d10", "#3d2408"],
  },
  wind: {
    light: ["#e6f3e9", "#c0e0c8", "#90c79e", "#5da672", "#38804d", "#1c5430"],
    dark: ["#a9e0b6", "#6fbc82", "#43955a", "#2c6f40", "#1e4d2c", "#14301c"],
  },
};

const OVERLAY_ALPHA = 0.72;
const ARROW_TARGET = 11;
const PLAY_MS = 450;

const basinCache = new Map<string, SwellBasin>();

/** Payloads published before 2026-07-26 carry grib-filter 0-360 longitudes
    (Portugal = 347.5); MapLibre wants signed degrees or it projects the field a
    world-copy off-screen. Harmless on already-canonical payloads. */
function normalizeBasin(b: SwellBasin): SwellBasin {
  const wrap = (lon: number) => (lon > 180 ? lon - 360 : lon);
  return { ...b, lon_first: wrap(b.lon_first), lon_last: wrap(b.lon_last) };
}

const ALL = "all";

async function loadBasin(name: string): Promise<SwellBasin> {
  const hit = basinCache.get(name);
  if (hit) return hit;
  const data = normalizeBasin(await fetchSwellBasin(name));
  basinCache.set(name, data);
  return data;
}

function rampColor(ramp: string[], t: number): string {
  return ramp[Math.min(ramp.length - 1, Math.floor(t * ramp.length))] ?? "#1d6f8c";
}

function cellValue(b: SwellBasin, f: SwellBasin["frames"][number], i: number, v: Variable): number | null {
  if (v === "wind") {
    const qw = f.wind?.[i];
    if (qw === undefined || qw === 255) return null;
    return qw * (b.scales.wind_ms ?? 0.25) * 1.94384; // knots, the app's wind unit
  }
  const qh = f.hs[i];
  if (qh === undefined || qh === 255) return null;
  if (v === "hs") return qh * b.scales.hs_m;
  const qp = f.per[i];
  if (qp === undefined || qp === 255) return null;
  const per = qp * b.scales.per_s;
  if (v === "per") return per;
  return 0.49 * (qh * b.scales.hs_m) ** 2 * (0.9 * per); // kW/m, Te = 0.9*Tp
}

function nearestBasin(index: SwellIndex, lat: number, lon: number): string | null {
  let best: string | null = null;
  let bestD = Infinity;
  for (const [name, e] of Object.entries(index)) {
    const [la0, lo0, la1, lo1] = e.bbox;
    if (lat >= la0 && lat <= la1 && lon >= lo0 && lon <= lo1) return name;
    const d = (lat - (la0 + la1) / 2) ** 2 + (lon - (lo0 + lo1) / 2) ** 2;
    if (d < bestD) {
      bestD = d;
      best = name;
    }
  }
  return best;
}

function timeLabel(iso: string): string {
  return new Date(iso.replace("Z", ":00Z")).toLocaleString(undefined, {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Ruler metadata per frame: local weekday, plus whether this frame opens a new
    local day (it gets the heavy tick + the day label on the timeline). */
function rulerMarks(timeline: string[]): { label: string; dayStart: boolean }[] {
  let prev = "";
  return timeline.map((iso) => {
    const d = new Date(iso.replace("Z", ":00Z"));
    const key = d.toDateString();
    const dayStart = prev !== "" && key !== prev;
    prev = key;
    return { label: d.toLocaleDateString(undefined, { weekday: "short" }), dayStart };
  });
}

function basinLabel(name: string): string {
  return name.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function ChartsPage({ theme }: { theme: "light" | "dark" }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [index, setIndex] = useState<SwellIndex | null>(null);
  const [basinName, setBasinName] = useState<string | null>(null);
  const [basins, setBasins] = useState<SwellBasin[]>([]);
  const [variable, setVariable] = useState<Variable>("hs");
  const [menuOpen, setMenuOpen] = useState(false);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Map + index once. The splash lifts as soon as we know what there is to show.
  useEffect(() => {
    let disposed = false;
    (async () => {
      try {
        const [{ default: maplibregl }, idx] = await Promise.all([
          import("maplibre-gl"),
          fetchSwellIndex(),
        ]);
        await import("maplibre-gl/dist/maplibre-gl.css");
        if (disposed || !wrapRef.current) return;
        setIndex(idx);
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
          center: [34.8, 32.3],
          zoom: 4,
          attributionControl: false,
        });
        m.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-left");
        mapRef.current = m;
        // open on the basin nearest the last map view's region: default Israel
        setBasinName(nearestBasin(idx, 32.1, 34.8));
      } catch {
        if (!disposed) setError("Charts aren't published yet - try again after the next forecast cycle.");
      } finally {
        signalReady();
      }
    })();
    return () => {
      disposed = true;
      mapRef.current?.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Basemap follows the theme without rebuilding the map.
  useEffect(() => {
    const m = mapRef.current;
    if (!m) return;
    const src = m.getSource("carto") as { setTiles?: (t: string[]) => void } | undefined;
    src?.setTiles?.([TILE_URLS[theme]]);
  }, [theme]);

  // Load the selection - one basin, or every published basin stitched onto one
  // chart ("All") - and frame the map on the union of what loaded.
  useEffect(() => {
    if (!basinName || !index) return;
    let disposed = false;
    (async () => {
      try {
        const names = basinName === ALL ? Object.keys(index) : [basinName];
        const settled = await Promise.allSettled(names.map(loadBasin));
        const loaded = settled
          .filter((r): r is PromiseFulfilledResult<SwellBasin> => r.status === "fulfilled")
          .map((r) => r.value);
        if (disposed) return;
        if (!loaded.length) {
          setError("This basin isn't published yet.");
          return;
        }
        setBasins(loaded);
        setFrame(0);
        const lons = loaded.flatMap((b) => [b.lon_first, b.lon_last]);
        const lats = loaded.flatMap((b) => [b.lat_first, b.lat_last]);
        mapRef.current?.fitBounds(
          [
            [Math.min(...lons), Math.min(...lats)],
            [Math.max(...lons), Math.max(...lats)],
          ],
          { padding: 20, duration: 600 },
        );
      } catch {
        if (!disposed) setError("This basin isn't published yet.");
      }
    })();
    return () => {
      disposed = true;
    };
  }, [basinName, index]);

  // Master timeline = the longest frame list; other basins join by timestamp, so
  // a basin that missed a NOMADS step skips that frame instead of drifting.
  const timeline = basins.reduce<string[]>(
    (best, b) => (b.frames.length > best.length ? b.frames.map((f) => f.t) : best),
    [],
  );

  // One fixed scale across every loaded basin and frame, so scrubbing - and the
  // stitched all-regions view - compare honestly.
  const maxVal = (() => {
    let mx = 0;
    for (const b of basins) {
      for (const f of b.frames) {
        for (let i = 0; i < f.hs.length; i++) {
          const v = cellValue(b, f, i, variable);
          if (v !== null && v > mx) mx = v;
        }
      }
    }
    return Math.max(1, Math.ceil(mx));
  })();

  // Draw the current frame; redraw on every map move so cells track the basemap.
  useEffect(() => {
    const m = mapRef.current;
    const canvas = canvasRef.current;
    const t = timeline[frame];
    if (!m || !canvas || !basins.length || !t) return;
    const ramp = RAMPS[variable][theme];

    const draw = () => {
      const wrap = canvas.parentElement;
      if (!wrap) return;
      const dpr = Math.min(2, devicePixelRatio || 1);
      const W = wrap.clientWidth;
      const H = wrap.clientHeight;
      if (canvas.width !== W * dpr) {
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = `${W}px`;
        canvas.style.height = `${H}px`;
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      const proj = (lat: number, lon: number) => m.project([lon, lat]);

      for (const bas of basins) {
        const f = bas.frames.find((fr) => fr.t === t);
        if (!f) continue; // this basin missed this NOMADS step - skip, don't drift
        ctx.globalAlpha = OVERLAY_ALPHA;
        const { nx, ny } = bas;
        const dLat = (bas.lat_last - bas.lat_first) / (ny - 1);
        const dLon = (bas.lon_last - bas.lon_first) / (nx - 1);

        for (let j = 0; j < ny; j++) {
          for (let i = 0; i < nx; i++) {
            const v = cellValue(bas, f, j * nx + i, variable);
            if (v === null) continue;
            const lat = bas.lat_first + j * dLat;
            const lon = bas.lon_first + i * dLon;
            const a = proj(lat - dLat / 2, lon - dLon / 2);
            const b = proj(lat + dLat / 2, lon + dLon / 2);
            const x = Math.min(a.x, b.x);
            const y = Math.min(a.y, b.y);
            const w = Math.abs(b.x - a.x) + 0.5;
            const h = Math.abs(b.y - a.y) + 0.5;
            if (x + w < 0 || y + h < 0 || x > W || y > H) continue;
            ctx.fillStyle = rampColor(ramp, Math.min(1, v / maxVal));
            ctx.fillRect(x, y, w, h);
          }
        }

        // Direction arrows - wind direction on the Wind chart, swell elsewhere.
        const cellPx = Math.abs(
          proj(bas.lat_first, bas.lon_first + dLon).x - proj(bas.lat_first, bas.lon_first).x,
        );
        const stride = Math.max(1, Math.round(W / ARROW_TARGET / Math.max(1, cellPx)));
        ctx.globalAlpha = 0.9;
        ctx.strokeStyle = theme === "dark" ? "rgba(255,255,255,0.85)" : "rgba(10,20,25,0.7)";
        ctx.lineWidth = 1.4;
        const len = Math.min(14, Math.max(7, cellPx * 0.45));
        for (let j = 0; j < ny; j += stride) {
          for (let i = 0; i < nx; i += stride) {
            const qd = (variable === "wind" ? f.wdir : f.dir)?.[j * nx + i];
            if (qd === undefined || qd === 255) continue;
            if (cellValue(bas, f, j * nx + i, variable === "wind" ? "wind" : "hs") === null) continue;
            const p = proj(bas.lat_first + j * dLat, bas.lon_first + i * dLon);
            if (p.x < 0 || p.y < 0 || p.x > W || p.y > H) continue;
            const rad = ((qd * bas.scales.dir_deg + 180) * Math.PI) / 180;
            const dx = Math.sin(rad) * len;
            const dy = -Math.cos(rad) * len;
            ctx.beginPath();
            ctx.moveTo(p.x - dx / 2, p.y - dy / 2);
            ctx.lineTo(p.x + dx / 2, p.y + dy / 2);
            const hx = p.x + dx / 2;
            const hy = p.y + dy / 2;
            const ang = Math.atan2(dy, dx);
            ctx.lineTo(hx - 4 * Math.cos(ang - 0.5), hy - 4 * Math.sin(ang - 0.5));
            ctx.moveTo(hx, hy);
            ctx.lineTo(hx - 4 * Math.cos(ang + 0.5), hy - 4 * Math.sin(ang + 0.5));
            ctx.stroke();
          }
        }
      }
      ctx.globalAlpha = 1;
    };

    draw();
    m.on("move", draw);
    return () => {
      m.off("move", draw);
      canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basins, frame, variable, theme, maxVal]);

  useEffect(() => {
    if (!playing || !timeline.length) return;
    const id = setInterval(() => setFrame((n) => (n + 1) % timeline.length), PLAY_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, timeline.length]);

  const t = timeline[frame];
  const ramp = basins.length ? RAMPS[variable][theme] : [];

  return (
    <main class="page map-page">
      <div class="map-screen">
        <div class="map-canvas" ref={wrapRef} />
        <canvas class="swell-canvas" ref={canvasRef} aria-hidden="true" />

        {index && (
          <div class="charts-basins" role="tablist" aria-label="Basin">
            {[ALL, ...Object.keys(index)].map((name) => (
              <button
                key={name}
                role="tab"
                aria-selected={name === basinName}
                class={`group-chip${name === basinName ? " on" : ""}`}
                onClick={() => setBasinName(name)}
              >
                {name === ALL ? "All regions" : basinLabel(name)}
              </button>
            ))}
          </div>
        )}

        {error && <p class="swell-note">{error}</p>}

        {basins.length > 0 && t && (
          <div class={`charts-deck${playing ? " playing" : ""}`}>
            <div class="deck-head">
              <button
                class="deck-tag"
                aria-haspopup="listbox"
                aria-expanded={menuOpen}
                onClick={() => setMenuOpen((o) => !o)}
              >
                {VARIABLES.find((v) => v.key === variable)?.label}
                <svg
                  class={`chev${menuOpen ? " up" : ""}`}
                  viewBox="0 0 10 6"
                  width="10"
                  height="6"
                  aria-hidden="true"
                >
                  <path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </button>
              {menuOpen && <div class="deck-scrim" onClick={() => setMenuOpen(false)} />}
              {menuOpen && (
                <div class="deck-menu" role="listbox" aria-label="Chart type">
                  {VARIABLES.filter((v) => v.key !== "wind" || basins.some((b) => b.frames[0]?.wind)).map((v) => (
                    <button
                      key={v.key}
                      role="option"
                      aria-selected={variable === v.key}
                      class={variable === v.key ? "on" : ""}
                      onClick={() => {
                        setVariable(v.key);
                        setMenuOpen(false);
                      }}
                    >
                      {v.label}
                    </button>
                  ))}
                  <span class="deck-run">GFS-Wave · run {timeLabel(basins[0]!.run)}</span>
                </div>
              )}
              <span class="deck-legend" style={`background:linear-gradient(90deg, ${ramp.join(",")})`} />
              <span class="deck-clock tabular">
                <small>{new Date(t.replace("Z", ":00Z")).toLocaleDateString(undefined, { weekday: "short" })}</small>
                {new Date(t.replace("Z", ":00Z")).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
              </span>
            </div>
            <div class="deck-timeline">
              <button
                class="deck-play"
                onClick={() => setPlaying((p) => !p)}
                aria-label={playing ? "Pause" : "Play"}
              >
                {playing ? (
                  <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                    <rect x="2" y="1.5" width="3" height="9" rx="1" fill="currentColor" />
                    <rect x="7" y="1.5" width="3" height="9" rx="1" fill="currentColor" />
                  </svg>
                ) : (
                  <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                    <path d="M3.2 1.6a1 1 0 0 1 1.5-.86l6.2 4.4a1 1 0 0 1 0 1.72l-6.2 4.4a1 1 0 0 1-1.5-.86z" fill="currentColor" />
                  </svg>
                )}
              </button>
              <div class="deck-ruler">
                <div class="deck-ticks" aria-hidden="true">
                  {rulerMarks(timeline).map((m, i) => (
                    <span key={i} class={`tick${m.dayStart ? " maj" : ""}`}>
                      {m.dayStart && i / (timeline.length - 1) < 0.94 && (
                        <span class="tklb">{m.label}</span>
                      )}
                    </span>
                  ))}
                </div>
                <span
                  class="deck-needle"
                  style={`left:${timeline.length > 1 ? (frame / (timeline.length - 1)) * 100 : 0}%`}
                  aria-hidden="true"
                />
                <input
                  class="deck-scrub"
                  type="range"
                  min={0}
                  max={timeline.length - 1}
                  value={frame}
                  aria-label="Forecast time"
                  onInput={(e) => {
                    setPlaying(false);
                    setFrame(Number((e.target as HTMLInputElement).value));
                  }}
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
