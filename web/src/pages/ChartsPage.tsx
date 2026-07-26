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
// Light theme deepens with magnitude; dark theme glows with magnitude.
const RAMPS: Record<Variable, { light: string[]; dark: string[] }> = {
  hs: {
    light: ["#dfeef4", "#b3d9e6", "#7cbcd2", "#4295b4", "#1d6f8c", "#0d4459"],
    dark: ["#0d3340", "#155163", "#20758c", "#3b9cb4", "#6cc3d8", "#a8e4f2"],
  },
  per: {
    light: ["#ece9f7", "#cdc5ee", "#a99add", "#8471c9", "#5e4aa8", "#3b2d75"],
    dark: ["#241d4e", "#3a2f7c", "#5443ab", "#7b68cc", "#a396dd", "#cfc7f2"],
  },
  energy: {
    light: ["#fdeedd", "#f8d3ab", "#f0b077", "#e08a4c", "#b96426", "#84440f"],
    dark: ["#3d2408", "#6b3d10", "#9c5a1c", "#cc7c30", "#eda45c", "#f9cf9b"],
  },
  wind: {
    light: ["#e6f3e9", "#c0e0c8", "#90c79e", "#5da672", "#38804d", "#1c5430"],
    dark: ["#14301c", "#1e4d2c", "#2c6f40", "#43955a", "#6fbc82", "#a9e0b6"],
  },
};

const OVERLAY_ALPHA = 0.72;
const ARROW_TARGET = 11;
const PLAY_MS = 450;

const basinCache = new Map<string, SwellBasin>();

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

function basinLabel(name: string): string {
  return name.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function ChartsPage({ theme }: { theme: "light" | "dark" }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [index, setIndex] = useState<SwellIndex | null>(null);
  const [basinName, setBasinName] = useState<string | null>(null);
  const [basin, setBasin] = useState<SwellBasin | null>(null);
  const [variable, setVariable] = useState<Variable>("hs");
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

  // Load the selected basin (cached) and frame the map on it.
  useEffect(() => {
    if (!basinName) return;
    let disposed = false;
    (async () => {
      try {
        const data =
          basinCache.get(basinName) ?? (await fetchSwellBasin(basinName));
        basinCache.set(basinName, data);
        if (disposed) return;
        setBasin(data);
        setFrame(0);
        mapRef.current?.fitBounds(
          [
            [data.lon_first, data.lat_first],
            [data.lon_last, data.lat_last],
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
  }, [basinName]);

  // Per-basin, per-variable fixed scale so scrubbing compares honestly.
  const maxVal = (() => {
    if (!basin) return 1;
    let mx = 0;
    for (const f of basin.frames) {
      for (let i = 0; i < f.hs.length; i++) {
        const v = cellValue(basin, f, i, variable);
        if (v !== null && v > mx) mx = v;
      }
    }
    return Math.max(1, Math.ceil(mx));
  })();

  // Draw the current frame; track every map move.
  useEffect(() => {
    const m = mapRef.current;
    const canvas = canvasRef.current;
    if (!m || !canvas || !basin) return;
    const ramp = RAMPS[variable][theme];
    const f = basin.frames[frame];
    if (!f) return;

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
      ctx.globalAlpha = OVERLAY_ALPHA;

      const { nx, ny } = basin;
      const dLat = (basin.lat_last - basin.lat_first) / (ny - 1);
      const dLon = (basin.lon_last - basin.lon_first) / (nx - 1);
      const proj = (lat: number, lon: number) => m.project([lon, lat]);

      for (let j = 0; j < ny; j++) {
        for (let i = 0; i < nx; i++) {
          const v = cellValue(basin, f, j * nx + i, variable);
          if (v === null) continue;
          const lat = basin.lat_first + j * dLat;
          const lon = basin.lon_first + i * dLon;
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

      // Direction arrows - the WIND chart shows wind direction, wave charts show
      // swell direction; both point where the flow travels, kept sparse.
      const cellPx = Math.abs(
        proj(basin.lat_first, basin.lon_first + dLon).x - proj(basin.lat_first, basin.lon_first).x,
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
          if (cellValue(basin, f, j * nx + i, variable === "wind" ? "wind" : "hs") === null) continue;
          const p = proj(basin.lat_first + j * dLat, basin.lon_first + i * dLon);
          if (p.x < 0 || p.y < 0 || p.x > W || p.y > H) continue;
          const rad = ((qd * basin.scales.dir_deg + 180) * Math.PI) / 180;
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
      ctx.globalAlpha = 1;
    };

    draw();
    m.on("move", draw);
    return () => {
      m.off("move", draw);
      canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    };
  }, [basin, frame, variable, theme, maxVal]);

  useEffect(() => {
    if (!playing || !basin) return;
    const id = setInterval(() => setFrame((n) => (n + 1) % basin.frames.length), PLAY_MS);
    return () => clearInterval(id);
  }, [playing, basin]);

  const f = basin?.frames[frame];
  const ramp = basin ? RAMPS[variable][theme] : [];
  const unit = VARIABLES.find((v) => v.key === variable)?.unit ?? "";

  return (
    <main class="page map-page">
      <div class="map-screen">
        <div class="map-canvas" ref={wrapRef} />
        <canvas class="swell-canvas" ref={canvasRef} aria-hidden="true" />

        {index && (
          <div class="charts-basins" role="tablist" aria-label="Basin">
            {Object.keys(index).map((name) => (
              <button
                key={name}
                role="tab"
                aria-selected={name === basinName}
                class={`group-chip${name === basinName ? " on" : ""}`}
                onClick={() => setBasinName(name)}
              >
                {basinLabel(name)}
              </button>
            ))}
          </div>
        )}

        {error && <p class="swell-note">{error}</p>}

        {basin && f && (
          <div class="swell-bar charts-bar">
            <div class="swell-row">
              <div class="segmented compact charts-vars" role="radiogroup" aria-label="Chart type">
                {VARIABLES.filter((v) => v.key !== "wind" || basin.frames[0]?.wind).map((v) => (
                  <button
                    key={v.key}
                    role="radio"
                    aria-checked={variable === v.key}
                    class={variable === v.key ? "on" : ""}
                    onClick={() => setVariable(v.key)}
                  >
                    {v.label}
                  </button>
                ))}
              </div>
              <span class="swell-time tabular">{timeLabel(f.t)}</span>
            </div>
            <div class="swell-row">
              <button
                class="swell-play"
                onClick={() => setPlaying((p) => !p)}
                aria-label={playing ? "Pause" : "Play"}
              >
                {playing ? "❚❚" : "▶"}
              </button>
              <input
                class="swell-scrub"
                type="range"
                min={0}
                max={basin.frames.length - 1}
                value={frame}
                aria-label="Forecast time"
                onInput={(e) => {
                  setPlaying(false);
                  setFrame(Number((e.target as HTMLInputElement).value));
                }}
              />
            </div>
            <div class="swell-row swell-meta">
              <span class="swell-legend" style={`background:linear-gradient(90deg, ${ramp.join(",")})`} />
              <span class="swell-scale tabular">
                0-{maxVal} {unit}
              </span>
              <span class="swell-attr">GFS-Wave · run {timeLabel(basin.run)}</span>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
