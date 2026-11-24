import { useEffect, useRef, useState } from "preact/hooks";
import type { Map as MLMap } from "maplibre-gl";
import { loadMaplibre } from "../maplibre";
import {
  fetchIndex,
  fetchSwellBasin,
  fetchSwellIndex,
  fetchWorldMeta,
  swellmapAsset,
  type SwellBasin,
  type SwellIndex,
  type WorldMeta,
} from "../api";
import { getPosition, type LatLon } from "../geo";
import { CompassNorthIcon, MinusIcon, PlusIcon, SearchIcon } from "../components/icons";
import { ShareButton } from "../components/parts";
import { MapSearch } from "./MapPage";
import type { IndexEntry } from "../types";
import { signalReady } from "../splash";
import { BAND_COLORS, BAND_PIXELS, bandLabels, bandOf, bandRange, bandScale } from "../lib/chartBands";
import { useUnits } from "../units";

/** Charts tab: animated basin wave fields (SwellMap v0.2), Surfline-style - a
    full-bleed map with a colormapped field, a chart-type selector, and a timeline.
    Deliberately separate from the Map tab, which is for finding spots.

    All three chart types render from the same published frames: height and peak
    period are stored; energy is derived here (P ~ 0.49 * H^2 * Te kW/m, Te = 0.9*Tp -
    the same convention as the hourly kJ column). Colour: 20 flat bands on a fixed
    scale, cold to hot, the same in both themes (`lib/chartBands.ts`) - a colour
    reads back to a value. Until 2026-11-24 this was a smooth single-hue ramp
    stretched to each run, which showed shape but not value. */

// OpenFreeMap vector basemaps - same source + attribution terms as the Map tab.
const STYLE_URLS = {
  dark: "https://tiles.openfreemap.org/styles/dark",
  light: "https://tiles.openfreemap.org/styles/positron",
};
const ATTRIBUTION = "OpenFreeMap © OpenMapTiles Data from OpenStreetMap";

type Variable = "hs" | "per" | "energy" | "wind";

const VARIABLES: { key: Variable; label: string }[] = [
  { key: "hs", label: "Height" },
  { key: "per", label: "Period" },
  { key: "energy", label: "Energy" },
  { key: "wind", label: "Wind" },
];

// Legend: one hard-edged block per band, in map order.
const LEGEND_BG = `linear-gradient(90deg, ${BAND_COLORS.map(
  (c, i) => `${c} ${(i * 100) / BAND_COLORS.length}% ${((i + 1) * 100) / BAND_COLORS.length}%`,
).join(",")})`;

// The basemap's sea: lakes are left out (the shore reach would paint ones near a coast).
const OCEAN = ["==", ["get", "class"], "ocean"] as ["==", ["get", string], string];

const OVERLAY_ALPHA = 0.72;
// shortcut: above this many pixels the field is painted smaller and scaled up
// (band edges soften a little on big screens), raise it if desktops show blur
const FIELD_MAX_PX = 1_000_000;
// How far the model's sea values are carried past its own coarse land mask
// (grid cells, ~50 km each on the world layer) before the basemap coast clips them.
const SHORE_REACH_CELLS = 2;
const ARROW_TARGET = 11;
const PLAY_MS = 450;

/* How far the wave field actually reaches. GFS-Wave carries values right over
   the pole (measured: to 89 N), so the north is limited only by mercator's own
   85.05 edge; the south stops at ~78.5 S, where the Southern Ocean gives way to
   the Antarctic ice shelf and there is nothing left to draw. The view is capped
   to this band (see minZoomFor): zooming out past it would only add blank. */
const DATA_LAT_N = 85.05;
const DATA_LAT_S = -78.5;
/* Opening zoom when we know where the user is: wide enough to hold the swell
   window feeding their coast, tight enough that their own sea is legible. */
const HOME_ZOOM = 3;

/** Mercator y of a latitude, 0 (north edge) to 1 (south edge). */
function mercY(lat: number): number {
  const clamped = Math.max(-DATA_LAT_N, Math.min(DATA_LAT_N, lat));
  return 0.5 - Math.log(Math.tan(Math.PI / 4 + (clamped * Math.PI) / 360)) / (2 * Math.PI);
}

/** Zoom at which the covered band exactly fills a viewport `h` CSS px tall -
    the chart's floor, so the field always reaches the top and bottom edges. */
function minZoomFor(h: number): number {
  const band = mercY(DATA_LAT_S) - mercY(DATA_LAT_N); // fraction of the world's height
  return Math.log2(Math.max(1, h) / (512 * band));
}

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

/** The drawn value at a point: the same bilinear read the field paints with. */
function sampleLayer(layer: Layer, vals: Float32Array, lon: number, lat: number): number | null {
  const { nx, ny } = layer;
  const turn = 360 / layer.dLon;
  let gx = (lon - layer.lon0) / layer.dLon;
  gx -= turn * Math.floor((gx + 0.5) / turn);
  const gy = (lat - layer.lat0) / layer.dLat;
  const wraps = Math.abs(turn - nx) < 1e-6;
  if (gy < -0.5 || gy > ny - 0.5 || (!wraps && gx > nx - 0.5)) return null;
  if (wraps && gx < 0) gx += nx;
  else if (!wraps) gx = Math.max(0, Math.min(nx - 1, gx));
  const y = Math.max(0, Math.min(ny - 1, gy));
  const a = Math.min(nx - 1, Math.floor(gx));
  const j = Math.floor(y);
  const b = wraps ? (a + 1) % nx : Math.min(nx - 1, a + 1);
  const fx = gx - a;
  const fy = y - j;
  const r1 = Math.min(ny - 1, j + 1) * nx;
  let w = 0;
  let sum = 0;
  for (const [i, k] of [
    [j * nx + a, (1 - fx) * (1 - fy)],
    [j * nx + b, fx * (1 - fy)],
    [r1 + a, (1 - fx) * fy],
    [r1 + b, fx * fy],
  ] as const) {
    const v = vals[i]!;
    if (v === v) ((w += k), (sum += k * v));
  }
  return w < 0.5 ? null : sum / w;
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
  // Tapped point: its band's range is printed there until the next tap.
  const probeRef = useRef<{ lng: number; lat: number } | null>(null);
  const probeElRef = useRef<HTMLDivElement>(null);
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
  const units = useUnits();
  const scale = bandScale(variable, units.height === "ft");
  const [bearing, setBearing] = useState(0);
  const [pos, setPos] = useState<LatLon | null>(null);
  const [spots, setSpots] = useState<[string, IndexEntry][] | null>(null);
  const [searching, setSearching] = useState(false);

  // Map + index once. The splash lifts as soon as we know what there is to show.
  useEffect(() => {
    let disposed = false;
    (async () => {
      try {
        const [maplibregl, idxR, worldR, at] = await Promise.all([
          loadMaplibre(),
          fetchSwellIndex().then(
            (v) => ({ ok: true as const, v }),
            () => ({ ok: false as const, v: null }),
          ),
          fetchWorldMeta().then(
            (v) => ({ ok: true as const, v }),
            () => ({ ok: false as const, v: null }),
          ),
          getPosition(), // cached session fix - no second permission prompt
        ]);
        await import("maplibre-gl/dist/maplibre-gl.css");
        if (disposed || !wrapRef.current) return;
        if (!worldR.ok) throw new Error("world chart not published");
        setPos(at);
        setIndex(idxR.v ?? {});
        setWorld(worldR.v);
        const m = new maplibregl.Map({
          container: wrapRef.current,
          style: STYLE_URLS[theme],
          // open on your own coast at basin scale - the swell heading at you is
          // the point; the whole world is one pinch away
          center: at ? [at.lon, at.lat] : [20, (DATA_LAT_N + DATA_LAT_S) / 2],
          zoom: at
            ? Math.max(HOME_ZOOM, minZoomFor(wrapRef.current.clientHeight))
            : minZoomFor(wrapRef.current.clientHeight),
          minZoom: minZoomFor(wrapRef.current.clientHeight),
          // the overlay is a flat canvas rotated with the bearing - it can turn
          // but not tilt, so pitch stays off
          maxPitch: 0,
          pitchWithRotate: false,
          attributionControl: false,
        });
        m.addControl(
          new maplibregl.AttributionControl({ compact: true, customAttribution: ATTRIBUTION }),
          "bottom-left"
        );
        // the floor follows the container (rotation, split screen, desktop resize)
        m.on("resize", () => m.setMinZoom(minZoomFor(m.getContainer().clientHeight)));
        // the north fab counter-rotates with the map and resets it on tap
        m.on("rotate", () => setBearing(m.getBearing()));
        // a tap on the sea reads the band there; a tap on land clears it
        m.on("click", (e) => {
          const onSea = !m.getLayer("water") || m.queryRenderedFeatures(e.point, { layers: ["water"], filter: OCEAN }).length > 0;
          probeRef.current = onSea ? e.lngLat : null;
          setTick((n) => n + 1);
        });
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

  // Basemap follows the theme without rebuilding the map. The chart overlay is a
  // canvas on top of the map, not a GL layer, so swapping the style leaves it alone.
  useEffect(() => {
    const m = mapRef.current;
    if (!m) return;
    m.setStyle(STYLE_URLS[theme]);
  }, [theme]);

  // Load the selection - the world layer, one basin, or every published basin
  // stitched onto one chart ("All") - and frame the map on what loaded.
  useEffect(() => {
    if (!basinName || !index) return;
    if (basinName === WORLD) {
      setBasins([]);
      setFrame(0);
      // no reframing: the map opens on the covered band and can't zoom out past it
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
  // basemap. Every screen pixel is sampled from the grid itself (bilinear in
  // lon/lat, mercator-exact) and THEN cut into its colour band, so band edges
  // are smooth contours on a fixed scale: the same colour is the same value on
  // every frame, run and sea. Colouring the cells first and letting the canvas
  // smooth them (the pre-2026-11-24 renderer) blurs the edges instead.
  useEffect(() => {
    const m = mapRef.current;
    const canvas = canvasRef.current;
    const t = timeline[frame];
    if (!m || !canvas || !t || (isWorld ? !world : !basins.length)) return;

    const step = scale.step;
    // physical values once per layer (NaN = land/missing), not once per pixel
    const valueGrids = new Map<string, Float32Array>();
    const valuesOf = (layer: Layer): Float32Array => {
      let vals = valueGrids.get(layer.id);
      if (!vals) {
        const { nx, ny } = layer;
        vals = new Float32Array(nx * ny);
        for (let i = 0; i < vals.length; i++) vals[i] = layer.val(i) ?? NaN;
        // The model's land mask is ~50 km blocks, so its sea stops short of the
        // real shore. Carry the nearest sea values a few cells inland; draw()
        // then clips the field to the basemap's own coastline.
        const wraps = Math.abs(layer.dLon * nx - 360) < 1e-6;
        for (let pass = 0; pass < SHORE_REACH_CELLS; pass++) {
          const prev = vals.slice();
          for (let j = 0; j < ny; j++) {
            for (let i = 0; i < nx; i++) {
              if (prev[j * nx + i] === prev[j * nx + i]) continue;
              let sum = 0;
              let cnt = 0;
              for (let dj = -1; dj <= 1; dj++) {
                const jj = j + dj;
                if (jj < 0 || jj >= ny) continue;
                for (let di = -1; di <= 1; di++) {
                  let ii = i + di;
                  if (wraps) ii = (ii + nx) % nx;
                  else if (ii < 0 || ii >= nx) continue;
                  const v = prev[jj * nx + ii]!;
                  if (v === v) ((sum += v), cnt++);
                }
              }
              if (cnt) vals[j * nx + i] = sum / cnt;
            }
          }
        }
        valueGrids.set(layer.id, vals);
      }
      return vals;
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

    const field = document.createElement("canvas"); // opaque banded field, reused per draw
    const sea = document.createElement("canvas"); // the field clipped to the basemap's sea

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
      const fctx = field.getContext("2d");
      if (!ctx || !fctx || !W || !H) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);

      // Draw in an unrotated (north-up) mercator plane and spin the whole canvas
      // by the map bearing around the screen centre, so the field and arrows
      // turn with the basemap. project() can't be used per axis once the map is
      // rotated: screen x then depends on latitude too.
      const center = m.getCenter();
      const sc = m.project(center);
      const angle = (-m.getBearing() * Math.PI) / 180; // maplibre: angle = -bearing
      ctx.translate(sc.x, sc.y);
      ctx.rotate(angle);
      ctx.translate(-sc.x, -sc.y);
      // the rotated screen fits inside this box of the unrotated plane
      const R = Math.hypot(W, H) / 2;
      const xMin = sc.x - R;
      const xMax = sc.x + R;
      const yMin = sc.y - R;
      const yMax = sc.y + R;

      // Continuous-plane mapping (no wrap): one world's pixel width lets any
      // longitude - including the 0-360 world grid - land on the right x, and
      // repeats the layer on the neighbouring world copies.
      const worldW = 512 * 2 ** m.getZoom();
      const mercY = (lat: number) =>
        (180 - (180 / Math.PI) * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))) / 360;
      const cMercY = mercY(center.lat);
      const xOfLon = (lon: number) => sc.x + ((lon - center.lng) / 360) * worldW;
      const yOfLat = (lat: number) =>
        sc.y + (mercY(Math.max(-DATA_LAT_N, Math.min(DATA_LAT_N, lat))) - cMercY) * worldW;

      // The field is painted in the unrotated plane: the screen itself, or the
      // box that holds it once the map is turned. Pixel count is capped - the
      // loop runs on every move - and the composite scales the result back up.
      const turned = angle !== 0;
      const bx0 = turned ? xMin : 0;
      const by0 = turned ? yMin : 0;
      const bw = turned ? 2 * R : W;
      const bh = turned ? 2 * R : H;
      const fs = Math.min(1, Math.sqrt(FIELD_MAX_PX / (bw * bh)));
      const fw = Math.max(1, Math.round(bw * fs));
      const fh = Math.max(1, Math.round(bh * fs));
      if (field.width !== fw || field.height !== fh) {
        field.width = fw;
        field.height = fh;
      }
      const img = fctx.createImageData(fw, fh);
      const out = new Uint32Array(img.data.buffer);
      const colA = new Int32Array(fw); // left cell of each pixel column, -1 = outside the grid
      const colB = new Int32Array(fw);
      const colF = new Float32Array(fw);

      for (const layer of layers) {
        const vals = valuesOf(layer);
        const { nx, ny, dLon, dLat } = layer;
        const wraps = Math.abs(dLon * nx - 360) < 1e-6; // the world grid closes on itself
        for (let px = 0; px < fw; px++) {
          const lon = center.lng + ((bx0 + ((px + 0.5) * bw) / fw - sc.x) / worldW) * 360;
          // column position within the copy of the world this pixel falls on
          let gx = (lon - layer.lon0) / dLon;
          const turn = 360 / dLon;
          gx -= turn * Math.floor((gx + 0.5) / turn);
          if (wraps) {
            const g = gx < 0 ? gx + nx : gx;
            const a = Math.min(nx - 1, Math.floor(g));
            colA[px] = a;
            colB[px] = (a + 1) % nx;
            colF[px] = g - a;
          } else if (gx > nx - 0.5) {
            colA[px] = -1;
          } else {
            const g = Math.max(0, Math.min(nx - 1, gx));
            const a = Math.floor(g);
            colA[px] = a;
            colB[px] = Math.min(nx - 1, a + 1);
            colF[px] = g - a;
          }
        }
        for (let py = 0; py < fh; py++) {
          const my = cMercY + (by0 + ((py + 0.5) * bh) / fh - sc.y) / worldW;
          const lat = ((2 * Math.atan(Math.exp(Math.PI * (1 - 2 * my))) - Math.PI / 2) * 180) / Math.PI;
          if (Math.abs(lat) > DATA_LAT_N) continue;
          const gy = (lat - layer.lat0) / dLat;
          if (gy < -0.5 || gy > ny - 0.5) continue;
          const g = Math.max(0, Math.min(ny - 1, gy));
          const j = Math.floor(g);
          const fy = g - j;
          const r0 = j * nx;
          const r1 = Math.min(ny - 1, j + 1) * nx;
          const o = py * fw;
          for (let px = 0; px < fw; px++) {
            const a = colA[px]!;
            if (a < 0) continue;
            const b = colB[px]!;
            const fx = colF[px]!;
            // bilinear over the cells that hold a value, as far as they carry
            // half the weight (the real coast is cut by the sea clip below)
            let w = 0;
            let sum = 0;
            let v = vals[r0 + a]!;
            if (v === v) ((w += (1 - fx) * (1 - fy)), (sum += (1 - fx) * (1 - fy) * v));
            v = vals[r0 + b]!;
            if (v === v) ((w += fx * (1 - fy)), (sum += fx * (1 - fy) * v));
            v = vals[r1 + a]!;
            if (v === v) ((w += (1 - fx) * fy), (sum += (1 - fx) * fy * v));
            v = vals[r1 + b]!;
            if (v === v) ((w += fx * fy), (sum += fx * fy * v));
            if (w < 0.5) continue;
            out[o + px] = BAND_PIXELS[bandOf(sum / w, step)]!;
          }
        }
      }
      fctx.putImageData(img, 0, 0);

      // Clip to the sea the basemap itself draws, so the field ends on the
      // coastline the user sees. Each polygon is filled on its own: tiles
      // overlap at their edges, and one shared path would fill islands there.
      // Lakes are left out - the reach above would paint ones near a coast.
      // Before the tiles land there is no sea to clip to: draw unclipped.
      const water = m.getLayer("water")
        ? m.queryRenderedFeatures({ layers: ["water"], filter: OCEAN })
        : [];
      let src: HTMLCanvasElement = field;
      const sctx = water.length ? sea.getContext("2d") : null;
      if (sctx) {
        if (sea.width !== canvas.width || sea.height !== canvas.height) {
          sea.width = canvas.width;
          sea.height = canvas.height;
        }
        sctx.globalCompositeOperation = "source-over";
        sctx.setTransform(1, 0, 0, 1, 0, 0);
        sctx.clearRect(0, 0, sea.width, sea.height);
        sctx.setTransform(ctx.getTransform());
        for (const f of water) {
          const g = f.geometry;
          const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
          for (const poly of polys) {
            sctx.beginPath();
            for (let k = -1; k <= 1; k++) {
              for (const ring of poly) {
                for (let i = 0; i < ring.length; i++) {
                  const x = xOfLon(ring[i]![0]!) + k * worldW;
                  const y = sc.y + (mercY(ring[i]![1]!) - cMercY) * worldW;
                  if (i) sctx.lineTo(x, y);
                  else sctx.moveTo(x, y);
                }
                sctx.closePath();
              }
            }
            sctx.fill("evenodd");
          }
        }
        sctx.globalCompositeOperation = "source-in";
        sctx.drawImage(field, bx0, by0, bw, bh);
        src = sea;
      }

      // one composite pass: the whole field fades over the basemap uniformly
      ctx.save();
      ctx.globalAlpha = OVERLAY_ALPHA;
      if (src === sea) {
        ctx.setTransform(1, 0, 0, 1, 0, 0); // already in screen pixels
        ctx.drawImage(sea, 0, 0);
      } else {
        // ctx carries the map's rotation; the field is in the unrotated plane
        ctx.drawImage(field, bx0, by0, bw, bh);
      }
      ctx.restore();

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
          if (Math.abs(lat) > DATA_LAT_N) continue;
          const y = yOfLat(lat);
          if (y < yMin || y > yMax) continue;
          for (let i = 0; i < layer.nx; i += stride) {
            const idx = j * layer.nx + i;
            const qd = layer.dirQ(idx);
            if (qd === 255) continue;
            if (layer.val(idx) === null) continue;
            const bx = xOfLon(layer.lon0 + i * layer.dLon);
            for (let k = -1; k <= 1; k++) {
              const x = bx + k * worldW;
              if (x < xMin || x > xMax) continue;
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

      // the tapped point's label rides the map and re-reads on every frame
      const probe = probeRef.current;
      const label = probeElRef.current;
      if (label) {
        let text = "";
        if (probe) {
          for (const layer of layers) {
            const v = sampleLayer(layer, valuesOf(layer), probe.lng, probe.lat);
            if (v !== null) text = bandRange(v, scale);
          }
        }
        label.hidden = !text;
        if (probe && text) {
          const at = m.project(probe);
          label.textContent = text;
          label.style.transform = `translate(${at.x}px, ${at.y}px) translate(-50%, calc(-100% - 9px))`;
        }
      }
    };

    draw();
    m.on("move", draw);
    m.on("idle", draw); // the sea clip follows the tiles as they load
    return () => {
      m.off("move", draw);
      m.off("idle", draw);
      canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basins, world, isWorld, frame, variable, theme, scale.step, tick]);

  useEffect(() => {
    if (!playing || !timeline.length) return;
    const id = setInterval(() => setFrame((n) => (n + 1) % timeline.length), PLAY_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, timeline.length]);

  // Publish the deck's live height as --sheet-h, the same way the Map screen does
  // for its card sheet, so maplibre's attribution chip rides just above it
  // instead of landing inside it.
  const deckObs = useRef<ResizeObserver | null>(null);
  const deckRef = (el: HTMLElement | null) => {
    deckObs.current?.disconnect();
    if (!el) return;
    const wrap = el.closest(".map-screen") as HTMLElement | null;
    if (!wrap) return;
    const apply = () => wrap.style.setProperty("--sheet-h", `${el.offsetHeight}px`);
    apply();
    deckObs.current = new ResizeObserver(apply);
    deckObs.current.observe(el);
  };

  // the spot list loads on the first search, not with the chart
  const openSearch = () => {
    setSearching(true);
    if (!spots)
      fetchIndex().then(
        (idx) => setSpots(Object.entries(idx.spots).sort(([, a], [, b]) => b.lat - a.lat)),
        () => {},
      );
  };
  const pick = (id: string) => {
    setSearching(false);
    const e = spots?.find(([k]) => k === id)?.[1];
    const m = mapRef.current;
    // coastal scale: the wave field is a ~25 km grid, a street zoom shows one cell
    if (e && m) m.easeTo({ center: [e.lon, e.lat], zoom: Math.max(m.getZoom(), 6), duration: 600 });
  };

  const t = timeline[frame];

  return (
    <main class="page map-page">
      <div class="map-screen">
        <div class="map-canvas" ref={wrapRef} />
        <canvas class="swell-canvas" ref={canvasRef} aria-hidden="true" />
        <div class="chart-probe tabular" ref={probeElRef} hidden />

        {error && <p class="swell-note">{error}</p>}

        <ShareButton class="map-fab share" path="/charts" />
        <button class="map-fab search" onClick={openSearch} aria-label="Search spots">
          <SearchIcon />
        </button>
        <button
          class="map-fab north"
          style={`--brg:${-bearing}deg`}
          onClick={() => mapRef.current?.resetNorth()}
          aria-label="Point north"
        >
          <CompassNorthIcon />
        </button>
        {/* Wide screens only (CSS): zoom without a wheel or a pinch. */}
        <button class="map-fab zoom-in" onClick={() => mapRef.current?.zoomIn()} aria-label="Zoom in">
          <PlusIcon />
        </button>
        <button class="map-fab zoom-out" onClick={() => mapRef.current?.zoomOut()} aria-label="Zoom out">
          <MinusIcon />
        </button>
        {searching && (
          <MapSearch spots={spots ?? []} pos={pos} onPick={pick} onClose={() => setSearching(false)} />
        )}

        {(isWorld ? world !== null : basins.length > 0) && t && (
          <div class={`charts-deck${playing ? " playing" : ""}`} ref={deckRef}>
            <div class="deck-card">
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
              <span class="deck-clock tabular">
                <small>{new Date(t.replace("Z", ":00Z")).toLocaleDateString(undefined, { weekday: "short" })}</small>
                {new Date(t.replace("Z", ":00Z")).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
              </span>
            </div>
            {/* The key: one block per band, the value at every second edge under it. */}
            <div class="deck-scale">
              <div class="deck-scale-bar">
                <span class="deck-legend" style={`background:${LEGEND_BG}`} />
                <span class="deck-nums tabular" aria-hidden="true">
                  {bandLabels(scale.shown).map((n, i, all) => (
                    <i key={n}>{i === all.length - 1 ? `${n}+` : n}</i>
                  ))}
                </span>
              </div>
              <span class="deck-unit">{scale.unit}</span>
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
          </div>
        )}
      </div>
    </main>
  );
}
