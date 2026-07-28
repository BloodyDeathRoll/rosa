import { useEffect, useRef, useState } from "preact/hooks";
import type { Map as MLMap } from "maplibre-gl";
import {
  fetchSwellBasin,
  fetchSwellIndex,
  fetchWorldMeta,
  swellmapAsset,
  type SwellBasin,
  type SwellIndex,
  type WorldMeta,
} from "../api";
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
const WORLD = "world";

async function loadBasin(name: string): Promise<SwellBasin> {
  const hit = basinCache.get(name);
  if (hit) return hit;
  const data = normalizeBasin(await fetchSwellBasin(name));
  basinCache.set(name, data);
  return data;
}

/* ---- World frames: lazy PNG fetch + decode ----------------------------------
   Each frame is one grayscale PNG of five field planes stacked vertically
   (hs, per, dir, wind, wdir). Decoded once into a flat byte buffer and cached
   for the session; frames load on demand while scrubbing. */

const worldPlaneCache = new Map<string, Uint8ClampedArray>();
const worldInflight = new Set<string>();

async function loadWorldFrame(meta: WorldMeta, png: string): Promise<void> {
  if (worldPlaneCache.has(png) || worldInflight.has(png)) return;
  worldInflight.add(png);
  try {
    const res = await fetch(swellmapAsset(png));
    if (!res.ok) return;
    // colorSpaceConversion none: the bytes ARE the data - no profile may touch them
    const bmp = await createImageBitmap(await res.blob(), {
      premultiplyAlpha: "none",
      colorSpaceConversion: "none",
    });
    const w = meta.nx;
    const h = meta.ny * meta.planes.length;
    const cnv = document.createElement("canvas");
    cnv.width = w;
    cnv.height = h;
    const cx = cnv.getContext("2d", { willReadFrequently: true });
    if (!cx) return;
    cx.drawImage(bmp, 0, 0);
    const rgba = cx.getImageData(0, 0, w, h).data;
    const out = new Uint8ClampedArray(w * h);
    for (let i = 0; i < out.length; i++) out[i] = rgba[i * 4]!; // grayscale: R channel
    worldPlaneCache.set(png, out);
  } finally {
    worldInflight.delete(png);
  }
}

/* ---- Colormap: 256-step LUT lerped across the ramp stops (matches the legend
   gradient) - the renderer paints per-cell pixels, not per-cell rects. */
const lutCache = new Map<string, Uint8ClampedArray>();

function rampLUT(variable: Variable, theme: "light" | "dark"): Uint8ClampedArray {
  const key = `${variable}|${theme}`;
  const hit = lutCache.get(key);
  if (hit) return hit;
  const stops = RAMPS[variable][theme].map((hex) => [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ]);
  const lut = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    const t = (i / 255) * (stops.length - 1);
    const a = Math.min(stops.length - 1, Math.floor(t));
    const b = Math.min(stops.length - 1, a + 1);
    const f = t - a;
    for (let c = 0; c < 3; c++) lut[i * 3 + c] = stops[a]![c]! * (1 - f) + stops[b]![c]! * f;
  }
  lutCache.set(key, lut);
  return lut;
}

/* ---- Layer: one drawable grid (a basin frame, or the world planes) ---------- */

interface Layer {
  id: string;
  nx: number;
  ny: number;
  lat0: number; // latitude of row 0 (either pole-first orientation works)
  dLat: number;
  lon0: number; // longitude of column 0 - may exceed 180 (world grid is 0-360)
  dLon: number;
  val: (i: number) => number | null; // selected variable, physical units
  dirQ: (i: number) => number; // quantized direction for arrows (255 = none)
  dirScale: number;
}

function basinLayer(bas: SwellBasin, f: SwellBasin["frames"][number], variable: Variable): Layer {
  return {
    id: bas.basin,
    nx: bas.nx,
    ny: bas.ny,
    lat0: bas.lat_first,
    dLat: (bas.lat_last - bas.lat_first) / (bas.ny - 1),
    lon0: bas.lon_first,
    dLon: (bas.lon_last - bas.lon_first) / (bas.nx - 1),
    val: (i) => cellValue(bas, f, i, variable),
    dirQ: (i) => (variable === "wind" ? (f.wdir?.[i] ?? 255) : (f.dir?.[i] ?? 255)),
    dirScale: bas.scales.dir_deg,
  };
}

function worldLayer(meta: WorldMeta, planes: Uint8ClampedArray, variable: Variable): Layer {
  const n = meta.nx * meta.ny;
  const P = (name: string) => meta.planes.indexOf(name) * n;
  const s = meta.scales;
  const val = (i: number): number | null => {
    if (variable === "wind") {
      const q = planes[P("wind") + i]!;
      return q === 255 ? null : q * s.wind_ms * 1.94384;
    }
    const qh = planes[P("hs") + i]!;
    if (qh === 255) return null;
    const hs = qh * s.hs_m;
    if (variable === "hs") return hs;
    const qp = planes[P("per") + i]!;
    if (qp === 255) return null;
    const per = qp * s.per_s;
    if (variable === "per") return per;
    return 0.49 * hs * hs * (0.9 * per);
  };
  return {
    id: "world",
    nx: meta.nx,
    ny: meta.ny,
    lat0: meta.lat_first,
    dLat: (meta.lat_last - meta.lat_first) / (meta.ny - 1),
    lon0: meta.lon_first,
    dLon: (meta.lon_last - meta.lon_first) / (meta.nx - 1),
    val,
    dirQ: (i) => planes[P(variable === "wind" ? "wdir" : "dir") + i]!,
    dirScale: s.dir_deg,
  };
}

/* Ramp-scale caps: the world's absolute max is a single typhoon cell - a linear
   ramp to it would flatten every ordinary coast. Saturate above these instead. */
const WORLD_SCALE_CAP: Record<Variable, number> = { hs: 8, per: 20, energy: 200, wind: 50 };

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

export function ChartsPage({ theme }: { theme: "light" | "dark" }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [index, setIndex] = useState<SwellIndex | null>(null);
  const [world, setWorld] = useState<WorldMeta | null>(null);
  const [basinName, setBasinName] = useState<string | null>(null);
  const [basins, setBasins] = useState<SwellBasin[]>([]);
  const [variable, setVariable] = useState<Variable>("hs");
  const [menuOpen, setMenuOpen] = useState(false);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [tick, setTick] = useState(0); // bumped when an async world frame lands
  const [error, setError] = useState<string | null>(null);

  // Map + index once. The splash lifts as soon as we know what there is to show.
  useEffect(() => {
    let disposed = false;
    (async () => {
      try {
        const [{ default: maplibregl }, idxR, worldR] = await Promise.all([
          import("maplibre-gl"),
          fetchSwellIndex().then(
            (v) => ({ ok: true as const, v }),
            () => ({ ok: false as const, v: null }),
          ),
          fetchWorldMeta().then(
            (v) => ({ ok: true as const, v }),
            () => ({ ok: false as const, v: null }),
          ),
        ]);
        await import("maplibre-gl/dist/maplibre-gl.css");
        if (disposed || !wrapRef.current) return;
        if (!worldR.ok) throw new Error("world chart not published");
        setIndex(idxR.v ?? {});
        setWorld(worldR.v);
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
          bounds: [
            [-179, -55],
            [179, 72],
          ],
          attributionControl: false,
        });
        m.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-left");
        mapRef.current = m;
        setBasinName(WORLD);
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

  // Load the selection - the world layer, one basin, or every published basin
  // stitched onto one chart ("All") - and frame the map on what loaded.
  useEffect(() => {
    if (!basinName || !index) return;
    if (basinName === WORLD) {
      setBasins([]);
      setFrame(0);
      mapRef.current?.fitBounds(
        [
          [-179, -55],
          [179, 72],
        ],
        { padding: 0, duration: 600 },
      );
      return;
    }
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

  const isWorld = basinName === WORLD;

  // Master timeline = the longest frame list; other basins join by timestamp, so
  // a basin that missed a NOMADS step skips that frame instead of drifting.
  const timeline = isWorld
    ? (world?.frames.map((f) => f.t) ?? [])
    : basins.reduce<string[]>(
        (best, b) => (b.frames.length > best.length ? b.frames.map((f) => f.t) : best),
        [],
      );

  // One fixed scale across every frame, so scrubbing compares honestly. World:
  // the pipeline precomputed the run's max (capped - see WORLD_SCALE_CAP).
  const maxVal = (() => {
    if (isWorld) {
      return Math.max(1, Math.ceil(Math.min(world?.max[variable] ?? 1, WORLD_SCALE_CAP[variable])));
    }
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

  // World frames load on demand: the shown frame first, then a short prefetch
  // run ahead so playback stays smooth once the first loop has warmed the cache.
  useEffect(() => {
    if (!isWorld || !world) return;
    const wanted = [frame, frame + 1, frame + 2].filter((i) => i < world.frames.length);
    for (const i of wanted) {
      const png = world.frames[i]!.png;
      if (!worldPlaneCache.has(png)) {
        void loadWorldFrame(world, png).then(() => setTick((n) => n + 1));
      }
    }
  }, [isWorld, world, frame]);

  // Draw the current frame; redraw on every map move so the field tracks the
  // basemap. Each layer is colormapped once into an offscreen grid canvas, then
  // blitted one latitude row at a time (mercator rows aren't evenly spaced) with
  // image smoothing on - bilinear interpolation instead of hard cell squares.
  useEffect(() => {
    const m = mapRef.current;
    const canvas = canvasRef.current;
    const t = timeline[frame];
    if (!m || !canvas || !t || (isWorld ? !world : !basins.length)) return;
    const lut = rampLUT(variable, theme);
    const gridCanvases = new Map<string, HTMLCanvasElement>();

    // Vertical oversampling: strips blit from a K-times-taller pre-upscaled
    // canvas, so the field is bilinear in BOTH axes (a 1-px source strip alone
    // interpolates horizontally only - basin zoom showed venetian-blind rows).
    const K = 8;

    const buildGrid = (layer: Layer): HTMLCanvasElement => {
      const cnv = document.createElement("canvas");
      cnv.width = layer.nx;
      cnv.height = layer.ny;
      const cx = cnv.getContext("2d")!;
      const img = cx.createImageData(layer.nx, layer.ny);
      const px = img.data;
      const n = layer.nx * layer.ny;
      // fully opaque pixels: strips may overlap while blitting, and translucent
      // overlaps would stack into visible seam lines - the whole field is
      // composited onto the map at OVERLAY_ALPHA in one pass instead
      for (let i = 0; i < n; i++) {
        const v = layer.val(i);
        if (v === null) continue; // land/missing stays transparent
        const q = Math.max(0, Math.min(255, Math.round((v / maxVal) * 255)));
        px[i * 4] = lut[q * 3]!;
        px[i * 4 + 1] = lut[q * 3 + 1]!;
        px[i * 4 + 2] = lut[q * 3 + 2]!;
        px[i * 4 + 3] = 255;
      }
      cx.putImageData(img, 0, 0);
      const tall = document.createElement("canvas");
      tall.width = layer.nx;
      tall.height = layer.ny * K;
      const tx = tall.getContext("2d")!;
      tx.imageSmoothingEnabled = true;
      tx.drawImage(cnv, 0, 0, layer.nx, layer.ny * K);
      return tall;
    };

    // World: draw the nearest loaded frame so scrubbing never flashes empty
    // while the target frame is still downloading.
    const currentLayers = (): Layer[] => {
      if (isWorld) {
        const frames = world!.frames;
        for (let d = 0; d < frames.length; d++) {
          for (const i of d === 0 ? [frame] : [frame - d, frame + d]) {
            if (i < 0 || i >= frames.length) continue;
            const planes = worldPlaneCache.get(frames[i]!.png);
            if (planes) return [worldLayer(world!, planes, variable)];
          }
        }
        return [];
      }
      const out: Layer[] = [];
      for (const bas of basins) {
        const f = bas.frames.find((fr) => fr.t === t);
        if (f) out.push(basinLayer(bas, f, variable)); // a missed NOMADS step skips, never drifts
      }
      return out;
    };
    const layers = currentLayers();

    const field = document.createElement("canvas"); // opaque strip target, reused per draw

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
      if (field.width !== W * dpr) {
        field.width = W * dpr;
        field.height = H * dpr;
      }
      const ctx = canvas.getContext("2d");
      const fctx = field.getContext("2d");
      if (!ctx || !fctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      fctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      fctx.clearRect(0, 0, W, H);
      fctx.imageSmoothingEnabled = true;

      // Continuous-plane x mapping (project() doesn't wrap): one world's pixel
      // width lets any longitude - including the 0-360 world grid - land on the
      // right screen x, and repeats the layer on the neighbouring world copies.
      const worldW = m.project([180, 0]).x - m.project([-180, 0]).x;
      const xOfLon = (lon: number) => m.project([-180, 0]).x + ((lon + 180) / 360) * worldW;
      const yOfLat = (lat: number) => m.project([0, Math.max(-85, Math.min(85, lat))]).y;

      for (const layer of layers) {
        let grid = gridCanvases.get(layer.id);
        if (!grid) {
          grid = buildGrid(layer);
          gridCanvases.set(layer.id, grid);
        }
        const xL = xOfLon(layer.lon0 - layer.dLon / 2);
        const spanW = ((layer.dLon * layer.nx) / 360) * worldW;

        for (let j = 0; j < layer.ny; j++) {
          const latA = layer.lat0 + (j - 0.5) * layer.dLat;
          const latB = layer.lat0 + (j + 0.5) * layer.dLat;
          // 79 deg trim: beyond it is the sea-ice margin's data/missing noise
          // (and mercator's blow-up) - no surf, no basin, nothing lost
          if (Math.max(Math.abs(latA), Math.abs(latB)) > 79) continue;
          const ya = yOfLat(latA);
          const yb = yOfLat(latB);
          const top = Math.min(ya, yb);
          const rowH = Math.abs(yb - ya);
          if (top > H || top + rowH < 0) continue;
          // subdivide tall rows so mercator row placement stays exact while the
          // pre-upscaled source supplies the vertical interpolation
          const S = Math.min(K, Math.max(1, Math.ceil(rowH / 3)));
          for (let s = 0; s < S; s++) {
            const fa = (j - 0.5 + s / S) * layer.dLat + layer.lat0;
            const fb = (j - 0.5 + (s + 1) / S) * layer.dLat + layer.lat0;
            const yfa = yOfLat(fa);
            const yfb = yOfLat(fb);
            const sy = Math.min(yfa, yfb);
            const sh = Math.abs(yfb - yfa);
            const srcY = j * K + (s * K) / S;
            for (let k = -1; k <= 1; k++) {
              const dx = k * worldW;
              if (xL + dx > W || xL + spanW + dx < 0) continue;
              // slight overlap so adjacent strips can't leave hairline seams -
              // harmless because the strips are opaque
              fctx.drawImage(grid, 0, srcY, layer.nx, K / S, xL + dx, sy, spanW, sh + 0.6);
            }
          }
        }
      }

      // one composite pass: the whole field fades over the basemap uniformly
      ctx.globalAlpha = OVERLAY_ALPHA;
      ctx.drawImage(field, 0, 0, W, H);
      ctx.globalAlpha = 1;

      for (const layer of layers) {
        // Direction arrows - wind direction on the Wind chart, swell elsewhere.
        const cellPx = (layer.dLon / 360) * worldW;
        const stride = Math.max(1, Math.round(W / ARROW_TARGET / Math.max(1, cellPx)));
        ctx.globalAlpha = 0.9;
        ctx.strokeStyle = theme === "dark" ? "rgba(255,255,255,0.85)" : "rgba(10,20,25,0.7)";
        ctx.lineWidth = 1.4;
        const len = Math.min(14, Math.max(7, cellPx * 0.45));
        for (let j = 0; j < layer.ny; j += stride) {
          const lat = layer.lat0 + j * layer.dLat;
          if (Math.abs(lat) > 79) continue;
          const y = yOfLat(lat);
          if (y < 0 || y > H) continue;
          for (let i = 0; i < layer.nx; i += stride) {
            const idx = j * layer.nx + i;
            const qd = layer.dirQ(idx);
            if (qd === 255) continue;
            if (layer.val(idx) === null) continue;
            const bx = xOfLon(layer.lon0 + i * layer.dLon);
            for (let k = -1; k <= 1; k++) {
              const x = bx + k * worldW;
              if (x < 0 || x > W) continue;
              const rad = ((qd * layer.dirScale + 180) * Math.PI) / 180;
              const ax = Math.sin(rad) * len;
              const ay = -Math.cos(rad) * len;
              ctx.beginPath();
              ctx.moveTo(x - ax / 2, y - ay / 2);
              ctx.lineTo(x + ax / 2, y + ay / 2);
              const hx = x + ax / 2;
              const hy = y + ay / 2;
              const ang = Math.atan2(ay, ax);
              ctx.lineTo(hx - 4 * Math.cos(ang - 0.5), hy - 4 * Math.sin(ang - 0.5));
              ctx.moveTo(hx, hy);
              ctx.lineTo(hx - 4 * Math.cos(ang + 0.5), hy - 4 * Math.sin(ang + 0.5));
              ctx.stroke();
            }
          }
        }
        ctx.globalAlpha = 1;
      }
    };

    draw();
    m.on("move", draw);
    return () => {
      m.off("move", draw);
      canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basins, world, isWorld, frame, variable, theme, maxVal, tick]);

  useEffect(() => {
    if (!playing || !timeline.length) return;
    const id = setInterval(() => setFrame((n) => (n + 1) % timeline.length), PLAY_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, timeline.length]);

  const t = timeline[frame];
  const ramp = RAMPS[variable][theme];

  return (
    <main class="page map-page">
      <div class="map-screen">
        <div class="map-canvas" ref={wrapRef} />
        <canvas class="swell-canvas" ref={canvasRef} aria-hidden="true" />

        {error && <p class="swell-note">{error}</p>}

        {(isWorld ? world !== null : basins.length > 0) && t && (
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
                  {VARIABLES.filter(
                    (v) => v.key !== "wind" || isWorld || basins.some((b) => b.frames[0]?.wind),
                  ).map((v) => (
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
                  <span class="deck-run">
                    GFS-Wave · run {timeLabel(isWorld ? world!.run : basins[0]!.run)}
                  </span>
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
