import { useEffect, useRef, useState } from "preact/hooks";
import { fetchIndex } from "../api";
import { ChevronLeftIcon, CompassNorthIcon, LocateIcon, SearchIcon } from "../components/icons";
import { SatMap } from "../components/MiniMap";
import { Pill, SpotTitle } from "../components/parts";
import { ratingVar } from "../conditions";
import { splitName } from "../format";
import { distanceKm, getPosition, refreshPosition, type LatLon } from "../geo";
import { signalReady } from "../splash";
import { boundsCenter, findRegion } from "../regions";
import { fmtRange, getUnits, useUnits } from "../units";
import type { IndexEntry } from "../types";
import type { Theme } from "../theme";
import type { Map as MLMap, Marker as MLMarker } from "maplibre-gl";

type Entry = [string, IndexEntry];

// CARTO raster basemaps (free tier, attribution required) - swap to self-hosted
// vector tiles before public launch.
const TILE_URLS: Record<Theme, string> = {
  dark: "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
  light: "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
};
const ATTRIBUTION = "© OpenStreetMap contributors © CARTO";

// Overlapping pins within this many screen pixels collapse into one count bubble.
const CLUSTER_PX = 46;

// Cards this many either side of the focused card load satellite imagery.
const IMG_WINDOW = 2;

// The bottom sheet is a single fixed-height card row; this much of the map's
// bottom edge is covered by it, so pins there aren't actually visible.
// (grip ~16 + card row ~122 + sheet padding ~18.)
const SHEET_H = 156;

/** "Show on map" hand-off from the spot screen: select this pin on next open. */
let pendingPin: string | null = null;
export function setPendingPin(id: string): void {
  pendingPin = id;
}

/** "Map area" hand-off from search: frame this region on next open. */
let pendingArea: string | null = null;
export function setPendingArea(region: string): void {
  pendingArea = region;
}

/** maplibre-gl is ~70 KB gz - loaded only when the Map tab opens. */
export function MapPage({ theme }: { theme: Theme }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const cardsRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);

  // spots + focus are read inside once-bound map event handlers, so they live in
  // refs alongside the React state that renders the carousel.
  const spotsRef = useRef<Entry[]>([]);
  const focusRef = useRef<string | null>(null);
  const posRef = useRef<LatLon | null>(null);
  const dotElsRef = useRef<Record<string, HTMLElement>>({}); // singleton pins, by id
  const markersRef = useRef<MLMarker[]>([]); // dot + cluster markers (rebuilt each move)
  const applyFocusRef = useRef<(id: string | null, fromScroll?: boolean) => void>(() => {});
  const scrollRafRef = useRef(0);
  const skipCenterRef = useRef(false); // don't fight a user-driven carousel scroll

  const [error, setError] = useState<string | null>(null);
  const [spots, setSpots] = useState<Entry[]>([]);
  const [visible, setVisible] = useState<string[]>([]);
  const [focus, setFocus] = useState<string | null>(null);
  const [pos, setPos] = useState<LatLon | null>(null);
  const [locState, setLocState] = useState<"idle" | "busy" | "fail">("idle");
  const [bearing, setBearing] = useState(0);
  const ensureYouRef = useRef<((p: LatLon) => void) | null>(null);
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState("");

  // Toggle the pill on the focused pin and remember it. `fromScroll` skips the
  // re-center effect so it doesn't yank a carousel the user is dragging.
  const applyFocus = (id: string | null, fromScroll = false) => {
    if (id === focusRef.current) return;
    const prev = focusRef.current;
    if (prev && dotElsRef.current[prev]) dotElsRef.current[prev].classList.remove("focus");
    if (id && dotElsRef.current[id]) dotElsRef.current[id].classList.add("focus");
    focusRef.current = id;
    skipCenterRef.current = fromScroll;
    setFocus(id);
  };
  applyFocusRef.current = applyFocus;

  useEffect(() => {
    let disposed = false;
    let map: MLMap | null = null;

    (async () => {
      try {
        const index = await fetchIndex();
        if (disposed) return;
        const ordered = Object.entries(index.spots).sort(([, a], [, b]) => b.lat - a.lat);
        spotsRef.current = ordered;
        setSpots(ordered);
        signalReady();

        const [{ default: maplibregl }, gpos] = await Promise.all([
          import("maplibre-gl"),
          getPosition(),
        ]);
        await import("maplibre-gl/dist/maplibre-gl.css");
        if (disposed || !wrapRef.current) return;
        posRef.current = gpos;
        setPos(gpos);

        // Search "map area" hand-off wins: frame the whole region.
        const area = pendingArea ? findRegion(index.spots, pendingArea) : undefined;
        pendingArea = null;

        // default focus: hand-off from a spot page > nearest to you > northernmost
        const nearest = gpos
          ? [...ordered].sort(
              ([, a], [, b]) =>
                distanceKm(gpos, { lat: a.lat, lon: a.lon }) -
                distanceKm(gpos, { lat: b.lat, lon: b.lon })
            )[0]?.[0]
          : ordered[0]?.[0];
        const handoff = !!(pendingPin && index.spots[pendingPin]);
        const start = area ? null : handoff ? pendingPin : (nearest ?? null);
        pendingPin = null;
        focusRef.current = start;
        setFocus(start);

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
          center: area
            ? boundsCenter(area.bounds)
            : startEntry
              ? [startEntry.lon, startEntry.lat]
              : gpos
                ? [gpos.lon, gpos.lat]
                : [34.8, 32.3],
          zoom: handoff ? 13 : 10,
          attributionControl: false,
        });
        map = m;
        mapRef.current = m;

        // Attribution is required (CARTO/OSM). Bottom-left, riding just above the
        // sheet (--sheet-h), themed via CSS; collapsed to the (i) by default -
        // it expands on tap, which satisfies the license terms. No zoom buttons.
        m.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-left");
        const collapseAttrib = () => {
          const d = m.getContainer().querySelector("details.maplibregl-ctrl-attrib");
          d?.removeAttribute("open");
          d?.classList.remove("maplibregl-compact-show");
        };
        collapseAttrib();
        m.once("load", collapseAttrib); // maplibre re-opens the compact control on load

        if (area) m.fitBounds(area.bounds, { padding: 56, maxZoom: 11, duration: 0 });

        let youMarker: MLMarker | null = null;
        const ensureYou = (p: LatLon) => {
          if (youMarker) {
            youMarker.setLngLat([p.lon, p.lat]);
            return;
          }
          const you = document.createElement("div");
          you.className = "you-dot";
          youMarker = new maplibregl.Marker({ element: you })
            .setLngLat([p.lon, p.lat])
            .addTo(m);
        };
        ensureYouRef.current = ensureYou;
        if (gpos) ensureYou(gpos);

        // the north fab counter-rotates with the map and resets it on tap
        m.on("rotate", () => setBearing(m.getBearing()));

        // Re-cluster the visible pins and rebuild the carousel list. Runs at rest
        // (load + moveend); markers auto-follow the map during a live pan.
        const recluster = () => {
          for (const mk of markersRef.current) mk.remove();
          markersRef.current = [];
          dotElsRef.current = {};

          const canvas = m.getCanvas();
          const W = canvas.clientWidth;
          const H = canvas.clientHeight;
          const pad = 90;

          type P = { id: string; e: IndexEntry; x: number; y: number };
          const pts: P[] = [];
          for (const [id, e] of spotsRef.current) {
            const p = m.project([e.lon, e.lat]);
            if (p.x < -pad || p.x > W + pad || p.y < -pad || p.y > H + pad) continue;
            pts.push({ id, e, x: p.x, y: p.y });
          }

          const used = new Set<string>();
          for (const p of pts) {
            if (used.has(p.id)) continue;
            used.add(p.id);
            const members: P[] = [p];
            for (const q of pts) {
              if (used.has(q.id)) continue;
              if (Math.hypot(p.x - q.x, p.y - q.y) < CLUSTER_PX) {
                used.add(q.id);
                members.push(q);
              }
            }
            if (members.length === 1) {
              const el = makeDot(p.id, p.e);
              dotElsRef.current[p.id] = el;
              markersRef.current.push(
                new maplibregl.Marker({ element: el }).setLngLat([p.e.lon, p.e.lat]).addTo(m)
              );
            } else {
              const lon = members.reduce((s, x) => s + x.e.lon, 0) / members.length;
              const lat = members.reduce((s, x) => s + x.e.lat, 0) / members.length;
              const es = members.map((x) => x.e);
              const el = makeCluster(es, () => fitToMembers(m, es));
              markersRef.current.push(
                new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(m)
              );
            }
          }

          // Carousel = spots actually visible on the map: on screen AND not hidden
          // behind the bottom sheet (a dot under the cards isn't "showing"). Ordered
          // S→N, so scrolling the cards to the right travels north up the coast the
          // same way the map does. spotsRef stays N→S for everything else.
          const visH = H - SHEET_H;
          const onScreen = (e: IndexEntry) => {
            const p = m.project([e.lon, e.lat]);
            return p.x >= 0 && p.x <= W && p.y >= 0 && p.y <= visH;
          };
          const inView = spotsRef.current.filter(([, e]) => onScreen(e));
          setVisible(inView.map(([id]) => id).reverse());

          // Keep the focus if still visible; else focus the spot nearest the
          // center of the *visible* strip (above the sheet).
          let f = focusRef.current;
          if (!f || !inView.some(([id]) => id === f)) {
            const c = m.unproject([W / 2, visH / 2]);
            f =
              inView
                .map(([id, e]) => ({
                  id,
                  d: distanceKm({ lat: c.lat, lon: c.lng }, { lat: e.lat, lon: e.lon }),
                }))
                .sort((a, z) => a.d - z.d)[0]?.id ?? null;
          }
          applyFocusRef.current(f);
        };

        const makeDot = (id: string, e: IndexEntry) => {
          const el = document.createElement("div");
          el.className = "spot-dot";
          el.dataset.id = id;
          el.style.setProperty("--tier", ratingVar(e.bucket));
          const label = document.createElement("span");
          label.className = "dot-label";
          label.textContent = fmtRange(e.h, getUnits(), false);
          el.appendChild(label);
          if (id === focusRef.current) el.classList.add("focus");
          el.addEventListener("click", (ev) => {
            ev.stopPropagation();
            applyFocusRef.current(id);
          });
          return el;
        };

        m.on("load", () => {
          m.resize(); // the container sizes via flex/absolute - measure once it's laid out
          recluster();
        });
        m.on("moveend", recluster);
      } catch {
        if (!disposed) setError("The map couldn't load. Check your connection and retry.");
      } finally {
        signalReady();
      }
    })();

    return () => {
      disposed = true;
      map?.remove();
      mapRef.current = null;
    };
  }, [theme]);

  // Center the focused card in the carousel - unless the focus came from the user
  // scrolling that same carousel.
  useEffect(() => {
    if (skipCenterRef.current) {
      skipCenterRef.current = false;
      return;
    }
    if (!focus) return;
    cardsRef.current
      ?.querySelector(`.map-card[data-id="${focus}"]`)
      ?.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
  }, [focus, visible]);

  // focus the field when search opens
  useEffect(() => {
    if (searching) searchRef.current?.focus();
  }, [searching]);

  // As the carousel scrolls, whichever card is nearest center becomes the focus.
  const onCardsScroll = () => {
    if (scrollRafRef.current) return;
    scrollRafRef.current = requestAnimationFrame(() => {
      scrollRafRef.current = 0;
      const track = cardsRef.current;
      if (!track) return;
      const mid = track.scrollLeft + track.clientWidth / 2;
      let best: string | null = null;
      let bestD = Infinity;
      for (const card of Array.from(track.querySelectorAll<HTMLElement>(".map-card"))) {
        const c = card.offsetLeft + card.offsetWidth / 2;
        const d = Math.abs(c - mid);
        if (d < bestD) {
          bestD = d;
          best = card.dataset.id ?? null;
        }
      }
      if (best) applyFocusRef.current(best, true);
    });
  };

  // The locate fab: geolocation can fail on first load (and getPosition caches
  // even that failure) - this forces a fresh fix and recenters on it.
  const locate = async () => {
    setLocState("busy");
    const p = await refreshPosition();
    const m = mapRef.current;
    if (!p || !m) {
      setLocState("fail");
      setTimeout(() => setLocState("idle"), 1800);
      return;
    }
    posRef.current = p;
    setPos(p);
    ensureYouRef.current?.(p);
    m.flyTo({ center: [p.lon, p.lat], zoom: Math.max(m.getZoom(), 10) });
    setLocState("idle");
  };

  // publish the sheet's live height so the attribution chip sits just above it
  const sheetObs = useRef<ResizeObserver | null>(null);
  const sheetRef = (el: HTMLElement | null) => {
    sheetObs.current?.disconnect();
    if (!el) return;
    const wrap = el.closest(".map-screen") as HTMLElement | null;
    if (!wrap) return;
    const apply = () => wrap.style.setProperty("--sheet-h", `${el.offsetHeight}px`);
    apply();
    sheetObs.current = new ResizeObserver(apply);
    sheetObs.current.observe(el);
  };

  const goBack = () => {
    if (history.length > 1) history.back();
    else location.hash = "#/today";
  };

  if (error) {
    return (
      <main class="page map-page">
        <div class="map-screen">
          <button class="map-fab back" onClick={goBack} aria-label="Back">
            <ChevronLeftIcon />
          </button>
          <p class="state">{error}</p>
        </div>
      </main>
    );
  }

  const byId = new Map(spots);
  const dist = (e: IndexEntry) =>
    pos ? Math.round(distanceKm(pos, { lat: e.lat, lon: e.lon })) : null;
  const focusIdx = focus ? visible.indexOf(focus) : -1;

  const q = query.trim().toLowerCase();
  const results = q
    ? spots.filter(
        ([id, e]) =>
          e.name.toLowerCase().includes(q) ||
          (e.region ?? "").toLowerCase().includes(q) ||
          id.includes(q)
      )
    : [];
  const closeSearch = () => {
    setSearching(false);
    setQuery("");
  };
  // Pick from search: zoom the (still-mounted) map into the spot; moveend then
  // rebuilds the carousel around it and its neighbours.
  const pick = (id: string) => {
    const e = byId.get(id);
    closeSearch();
    if (!e) return;
    focusRef.current = id;
    setFocus(id);
    const m = mapRef.current;
    m?.easeTo({ center: [e.lon, e.lat], zoom: Math.max(m.getZoom(), 13), duration: 600 });
  };

  return (
    <main class="page map-page">
      <div class="map-screen">
        <div class="map-canvas" ref={wrapRef} />
        <button class="map-fab back" onClick={goBack} aria-label="Back">
          <ChevronLeftIcon />
        </button>
        <button class="map-fab search" onClick={() => setSearching(true)} aria-label="Search spots">
          <SearchIcon />
        </button>
        <button
          class={`map-fab locate${locState === "fail" ? " err" : ""}`}
          onClick={() => void locate()}
          disabled={locState === "busy"}
          aria-label="Go to my location"
        >
          <LocateIcon />
        </button>
        <button
          class="map-fab north"
          style={`--brg:${-bearing}deg`}
          onClick={() => mapRef.current?.resetNorth()}
          aria-label="Point north"
        >
          <CompassNorthIcon />
        </button>
        <div class="map-sheet" ref={sheetRef}>
          <span class="sheet-grip" aria-hidden="true" />
          {visible.length ? (
            <div class="map-cards" ref={cardsRef} onScroll={onCardsScroll}>
              {visible.map((id, i) => {
                const e = byId.get(id);
                if (!e) return null;
                // Cap satellite loads to the focused card ± a couple of neighbours
                // (the rest aren't on screen until scrolled near).
                const img = focusIdx < 0 ? i < IMG_WINDOW * 2 + 1 : Math.abs(i - focusIdx) <= IMG_WINDOW;
                return (
                  <MapCard key={id} id={id} entry={e} dist={dist(e)} center={id === focus} img={img} />
                );
              })}
            </div>
          ) : (
            <p class="sheet-empty">Pan or zoom out to find spots.</p>
          )}
        </div>

        {/* Search layers over the live map so easeTo/pick keep working. */}
        {searching && (
          <div class="map-search">
            <header class="search-head">
              <button class="spot-back" onClick={closeSearch} aria-label="Close search">
                <ChevronLeftIcon />
              </button>
              <div class="search-box grow">
                <SearchIcon size={16} />
                <input
                  ref={searchRef}
                  placeholder="Search spots"
                  aria-label="Search spots"
                  value={query}
                  onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
                />
              </div>
            </header>
            <div class="map-locations">
              {q ? (
                results.length ? (
                  results.map(([id, e]) => (
                    <MapRow key={id} entry={e} dist={dist(e)} onSelect={() => pick(id)} />
                  ))
                ) : (
                  <p class="search-empty">No spots match “{query}”.</p>
                )
              ) : (
                <p class="search-empty">Search for a spot - the map opens to it.</p>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

/** Fit the map to a set of spots (used when a cluster bubble is tapped). */
function fitToMembers(m: MLMap, members: IndexEntry[]): void {
  let w = Infinity;
  let s = Infinity;
  let e = -Infinity;
  let n = -Infinity;
  for (const p of members) {
    w = Math.min(w, p.lon);
    e = Math.max(e, p.lon);
    s = Math.min(s, p.lat);
    n = Math.max(n, p.lat);
  }
  m.fitBounds(
    [
      [w, s],
      [e, n],
    ],
    { padding: 90, maxZoom: m.getZoom() + 3, duration: 500 }
  );
}

const TIER_RANK: Record<string, number> = { FLAT: 0, POOR: 1, FAIR: 2, GOOD: 3, FIRING: 4 };

/** Count bubble for overlapping pins. The ring is a conic blend of the members'
    tier colors (equal slice per spot), so a 2×green + 2×yellow cluster reads as
    half green, half yellow. */
function makeCluster(entries: IndexEntry[], onClick: () => void): HTMLElement {
  const sorted = [...entries].sort((a, b) => (TIER_RANK[a.bucket] ?? 0) - (TIER_RANK[b.bucket] ?? 0));
  const n = sorted.length;
  const stops = sorted
    .map((e, i) => `${ratingVar(e.bucket)} ${((i / n) * 360).toFixed(1)}deg ${(((i + 1) / n) * 360).toFixed(1)}deg`)
    .join(", ");
  const el = document.createElement("div");
  el.className = "map-cluster";
  el.style.background = `conic-gradient(${stops})`;
  const inner = document.createElement("span");
  inner.className = "map-cluster-inner";
  inner.textContent = String(n);
  el.appendChild(inner);
  el.addEventListener("click", (ev) => {
    ev.stopPropagation();
    onClick();
  });
  return el;
}

const CARD_H = 118;

/** The one big centered card drives the emphasized pin; tapping opens the spot.
    Satellite imagery of the break, dimmed, with the readout laid over it. */
function MapCard({
  id,
  entry,
  dist,
  center,
  img,
}: {
  id: string;
  entry: IndexEntry;
  dist: number | null;
  center: boolean;
  img: boolean;
}) {
  const units = useUnits();
  const { name, region } = splitName(entry.name);
  const sub = dist !== null ? `${dist} km${region ? ` · ${region}` : ""}` : region || "";
  return (
    <a class={`map-card${center ? " center" : ""}${img ? "" : " noimg"}`} data-id={id} href={`#/spot/${id}`}>
      {img && (
        <span class="map-card-bg">
          {entry.cam ? (
            // A spot with a cam shows what the camera sees rather than a satellite view -
            // YouTube's own still for the live stream, refreshed by them, credited in full
            // on the spot page one tap away.
            <img
              class="map-card-cam"
              src={`https://i.ytimg.com/vi/${entry.cam}/mqdefault.jpg`}
              alt=""
              loading="lazy"
              decoding="async"
            />
          ) : (
            <SatMap lat={entry.lat} lon={entry.lon} height={CARD_H} pin={false} />
          )}
        </span>
      )}
      <span class="map-card-shade" />
      <span class="map-card-body">
        <span class="map-card-head">
          <Pill bucket={entry.bucket} />
          {entry.cam && <span class="map-card-live">live cam</span>}
        </span>
        <span class="map-card-name">
          <SpotTitle name={name} region={null} />
        </span>
        <span class="map-card-h tabular">{fmtRange(entry.h, units)}</span>
        {sub && <span class="map-card-sub tabular">{sub}</span>}
      </span>
    </a>
  );
}

/** Compact spot row used only in the search overlay - frames the spot. */
function MapRow({
  entry,
  dist,
  onSelect,
}: {
  entry: IndexEntry;
  dist: number | null;
  onSelect: () => void;
}) {
  const units = useUnits();
  const { name, region } = splitName(entry.name);
  const sub = dist !== null ? `${dist} km` : region || fmtRange(entry.h, units);
  return (
    <div class="map-loc">
      <button class="map-loc-main" onClick={onSelect}>
        <span class="tier-dot" style={`background:${ratingVar(entry.bucket)}`} aria-hidden="true" />
        <span class="mid">
          <SpotTitle name={name} region={dist !== null ? region : ""} />
          <span class="line tabular">{sub}</span>
        </span>
      </button>
    </div>
  );
}
