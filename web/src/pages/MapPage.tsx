import { useEffect, useRef, useState } from "preact/hooks";
import { fetchIndex } from "../api";
import { ChevronLeftIcon, SearchIcon } from "../components/icons";
import { GroupChips, groupsOf, ALL_GROUP } from "../components/GroupChips";
import { AppHeader, SpotTitle, StarButton, TierDot } from "../components/parts";
import { ratingVar } from "../conditions";
import { getFavorites, toggleFavorite } from "../favorites";
import { splitName } from "../format";
import { distanceKm, getPosition, type LatLon } from "../geo";
import { signalReady } from "../splash";
import { boundsCenter, findRegion } from "../regions";
import { fmtRange, useUnits } from "../units";
import type { IndexEntry } from "../types";
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

/** "Map area" hand-off from search: frame this region on next open. */
let pendingArea: string | null = null;
export function setPendingArea(region: string): void {
  pendingArea = region;
}

interface MapHandle {
  easeTo(opts: { center: [number, number]; duration?: number; offset?: [number, number] }): void;
  fitBounds(
    bounds: [[number, number], [number, number]],
    opts?: { padding?: number; maxZoom?: number; duration?: number }
  ): void;
  remove(): void;
}

/** maplibre-gl is ~70 KB gz — loaded only when the Map tab opens. */
export function MapPage({ theme }: { theme: Theme }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const mapRef = useRef<MapHandle | null>(null);
  const dotsRef = useRef<Record<string, HTMLElement>>({});
  const [error, setError] = useState<string | null>(null);
  const [spots, setSpots] = useState<Entry[]>([]);
  const [pin, setPin] = useState<string | null>(null);
  const [pos, setPos] = useState<LatLon | null>(null);
  const [tab, setTab] = useState<"fav" | "near">("fav");
  const [group, setGroup] = useState<string>(ALL_GROUP);
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState("");
  const [favs, setFavs] = useState<string[]>(getFavorites);
  const onToggleFav = (id: string) => setFavs(toggleFavorite(id));

  useEffect(() => {
    let disposed = false;
    let map: MapHandle | null = null;

    (async () => {
      try {
        // Load the list first and lift the splash immediately — the map shell
        // (header · tabs · list) is ready before the heavy maplibre bundle and
        // geolocation resolve, so the Map tab appears instantly.
        const index = await fetchIndex();
        if (disposed) return;
        const ordered = Object.entries(index.spots).sort(([, a], [, b]) => b.lat - a.lat);
        setSpots(ordered);
        setTab(getFavorites().some((id) => index.spots[id]) ? "fav" : "near");
        signalReady();

        const [{ default: maplibregl }, gpos] = await Promise.all([
          import("maplibre-gl"),
          getPosition(),
        ]);
        await import("maplibre-gl/dist/maplibre-gl.css");
        if (disposed || !wrapRef.current) return;
        setPos(gpos);

        // Search "map area" hand-off wins: frame the whole region, no pin selected.
        const area = pendingArea ? findRegion(index.spots, pendingArea) : undefined;
        pendingArea = null;

        // default pin: hand-off from a spot page > nearest to you > northernmost
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
          center: area
            ? boundsCenter(area.bounds)
            : startEntry
              ? [startEntry.lon, startEntry.lat]
              : gpos
                ? [gpos.lon, gpos.lat]
                : [34.8, 32.3],
          zoom: handoff ? 13 : 9,
          attributionControl: { compact: true },
        });
        map = m as unknown as MapHandle;
        mapRef.current = map;

        if (area) m.fitBounds(area.bounds, { padding: 56, maxZoom: 11, duration: 0 });

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

        if (gpos) {
          const you = document.createElement("div");
          you.className = "you-dot";
          new maplibregl.Marker({ element: you }).setLngLat([gpos.lon, gpos.lat]).addTo(m);
        }
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

  // selected pin: ring the dot + center the map on it
  useEffect(() => {
    for (const [sid, dot] of Object.entries(dotsRef.current))
      dot.classList.toggle("active", sid === pin);
    if (!pin) return;
    const entry = spots.find(([sid]) => sid === pin);
    if (entry) mapRef.current?.easeTo({ center: [entry[1].lon, entry[1].lat], duration: 400 });
  }, [pin, spots]);

  // focus the field when search opens
  useEffect(() => {
    if (searching) searchRef.current?.focus();
  }, [searching]);

  if (error) {
    return (
      <main class="page">
        <AppHeader right={<span class="head-note">Map</span>} />
        <p class="state">{error}</p>
      </main>
    );
  }

  const dist = (e: IndexEntry) =>
    pos ? Math.round(distanceKm(pos, { lat: e.lat, lon: e.lon })) : null;

  // list for the active tab; while searching, the query filters all spots
  const q = query.trim().toLowerCase();
  const results = q
    ? spots.filter(
        ([id, e]) =>
          e.name.toLowerCase().includes(q) ||
          (e.region ?? "").toLowerCase().includes(q) ||
          id.includes(q)
      )
    : [];
  const favList = spots.filter(([id]) => favs.includes(id));
  const favGroups = groupsOf(favList);
  const activeGroup = favGroups.includes(group) ? group : ALL_GROUP;
  const favShown =
    activeGroup === ALL_GROUP
      ? favList
      : favList.filter(([, e]) => (e.region?.trim() || "Other") === activeGroup);
  const nearList = pos
    ? [...spots].sort(
        ([, a], [, b]) =>
          distanceKm(pos, { lat: a.lat, lon: a.lon }) - distanceKm(pos, { lat: b.lat, lon: b.lon })
      )
    : spots;
  const list = tab === "fav" ? favShown : nearList;

  // selecting from search centers the map on the spot and closes search
  const pickFromSearch = (id: string) => {
    setPin(id);
    setSearching(false);
    setQuery("");
  };

  const searchIcon = (
    <button class="icon-btn" onClick={() => setSearching(true)} aria-label="Search spots">
      <SearchIcon />
    </button>
  );

  return (
    <main class="page">
      {searching ? (
        <header class="search-head">
          <button
            class="spot-back"
            onClick={() => {
              setSearching(false);
              setQuery("");
            }}
            aria-label="Close search"
          >
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
      ) : (
        <AppHeader right={searchIcon} />
      )}
      <div class="map-screen">
        <div class="map-canvas" ref={wrapRef} />
        {!searching && (
          <div class="map-tabbar" role="tablist" aria-label="Map spots">
            <button
              role="tab"
              aria-selected={tab === "fav"}
              class={tab === "fav" ? "on" : ""}
              onClick={() => setTab("fav")}
            >
              Favourites
            </button>
            <button
              role="tab"
              aria-selected={tab === "near"}
              class={tab === "near" ? "on" : ""}
              onClick={() => setTab("near")}
            >
              Nearby
            </button>
          </div>
        )}
        {!searching && tab === "fav" && favGroups.length > 1 && (
          <GroupChips groups={favGroups} selected={activeGroup} onSelect={setGroup} />
        )}
        <div class="map-locations">
          {searching ? (
            q ? (
              results.length ? (
                results.map(([id, e]) => (
                  <MapRow
                    key={id}
                    entry={e}
                    dist={dist(e)}
                    active={id === pin}
                    isFav={favs.includes(id)}
                    onSelect={() => pickFromSearch(id)}
                    onToggleFav={() => onToggleFav(id)}
                  />
                ))
              ) : (
                <p class="search-empty">No spots match “{query}”.</p>
              )
            ) : (
              <p class="search-empty">Search for a spot — the map opens to it.</p>
            )
          ) : list.length ? (
            list.map(([id, e]) => (
              <MapRow
                key={id}
                entry={e}
                dist={dist(e)}
                active={id === pin}
                isFav={favs.includes(id)}
                onSelect={() => setPin(id)}
                onToggleFav={() => onToggleFav(id)}
              />
            ))
          ) : (
            <p class="search-empty">{tab === "fav" ? "No favourites yet." : "No spots nearby."}</p>
          )}
        </div>
      </div>
    </main>
  );
}

/** A spot row in the map list — the main area centers/rings the pin on the map
    above (never navigates); the star toggles favorites in place. */
function MapRow({
  entry,
  dist,
  active,
  isFav,
  onSelect,
  onToggleFav,
}: {
  entry: IndexEntry;
  dist: number | null;
  active: boolean;
  isFav: boolean;
  onSelect: () => void;
  onToggleFav: () => void;
}) {
  const units = useUnits();
  const { name, region } = splitName(entry.name);
  const sub = dist !== null ? `${dist} km` : region || fmtRange(entry.h, units);
  return (
    <div class={`map-loc${active ? " active" : ""}`}>
      <button class="map-loc-main" onClick={onSelect}>
        <TierDot bucket={entry.bucket} />
        <span class="mid">
          <SpotTitle name={name} region={dist !== null ? region : ""} />
          <span class="line tabular">{sub}</span>
        </span>
      </button>
      <StarButton on={isFav} name={name} size={16} onToggle={onToggleFav} />
    </div>
  );
}
