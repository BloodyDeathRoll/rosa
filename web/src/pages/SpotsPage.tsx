import { useEffect, useMemo, useState } from "preact/hooks";
import { fetchIndex, fetchSpot } from "../api";
import { ChevronRightIcon, MapPinIcon, SearchIcon } from "../components/icons";
import { AppHeader, SpotTitle, StarButton, TierDot } from "../components/parts";
import { SpotCard } from "../components/SpotCard";
import { ratingWord } from "../conditions";
import { getFavorites, toggleFavorite } from "../favorites";
import { signalReady } from "../splash";
import { bestWindow, dateOf, splitName, windLabel } from "../format";
import { distanceKm, getPosition, type LatLon } from "../geo";
import { regionsFrom, type RegionInfo } from "../regions";
import { fmtH, fmtRange, heightUnit, useUnits, type Units } from "../units";
import type { IndexEntry, SpotPayload } from "../types";
import { setPendingArea } from "./MapPage";

type Entry = [string, IndexEntry];

/** Spots shown under "Nearby" before the user searches — keeps the initial view scannable. */
const NEARBY_LIMIT = 5;

/** Group entries by their map area (region), preserving the incoming (N→S / nearest) order. */
function groupByRegion(rows: Entry[]): [string, Entry[]][] {
  const groups = new Map<string, Entry[]>();
  for (const row of rows) {
    const region = row[1].region?.trim() || "Other";
    const list = groups.get(region);
    if (list) list.push(row);
    else groups.set(region, [row]);
  }
  return [...groups.entries()];
}

function payloadLine(data: SpotPayload, units: Units): string {
  const cur = data.current;
  const today = data.hours.filter((h) => dateOf(h.t) === dateOf(data.hours[0]?.t ?? ""));
  const bw = bestWindow(today);
  return `${fmtH(cur.h_mid, units)} ${heightUnit(units)} · ${windLabel(cur)} · best ${bw ? bw.start : "—"}`;
}

function Row({
  id,
  entry,
  payload,
  isFav,
  onToggle,
}: {
  id: string;
  entry: IndexEntry;
  payload: SpotPayload | undefined;
  isFav: boolean;
  onToggle: () => void;
}) {
  const units = useUnits();
  const { name, region } = splitName(entry.name);
  // whole row navigates to the spot; the star swallows its own click (favorites)
  return (
    <a class="spot-row-card" href={`#/spot/${id}`}>
      <TierDot bucket={entry.bucket} />
      <span class="mid">
        <SpotTitle name={name} region={region} />
        <span class="line tabular">
          {payload ? payloadLine(payload, units) : `${fmtRange(entry.h, units)} · ${ratingWord(entry.bucket)}`}
        </span>
      </span>
      <StarButton on={isFav} name={name} size={16} onToggle={onToggle} />
    </a>
  );
}

/** A searchable "map area": tapping frames the whole region on the Map tab. */
function RegionRow({ region }: { region: RegionInfo }) {
  return (
    <a class="spot-row-card area-row" href="#/map" onClick={() => setPendingArea(region.name)}>
      <span class="area-pin">
        <MapPinIcon size={18} />
      </span>
      <span class="mid">
        <span class="spot-title">
          <b>{region.name}</b>
        </span>
        <span class="line">
          {region.count} spot{region.count === 1 ? "" : "s"} · view on map
        </span>
      </span>
      <ChevronRightIcon size={16} />
    </a>
  );
}

export function SpotsPage() {
  const [index, setIndex] = useState<Record<string, IndexEntry> | null>(null);
  const [payloads, setPayloads] = useState<Record<string, SpotPayload>>({});
  const [error, setError] = useState<string | null>(null);
  const [pos, setPos] = useState<LatLon | null>(null);
  const [query, setQuery] = useState("");
  const [favs, setFavs] = useState<string[]>(getFavorites);
  const onToggle = (id: string) => setFavs(toggleFavorite(id));

  useEffect(() => {
    let disposed = false;
    (async () => {
      try {
        const [idx, p] = await Promise.all([fetchIndex(), getPosition()]);
        if (disposed) return;
        setIndex(idx.spots);
        setPos(p);
        // every row carries the mock's detail line (wind + best window),
        // so every listed spot needs its payload — small files, CDN-cached
        const results = await Promise.allSettled(Object.keys(idx.spots).map(fetchSpot));
        if (disposed) return;
        const loaded: Record<string, SpotPayload> = {};
        for (const r of results) if (r.status === "fulfilled") loaded[r.value.spot.id] = r.value;
        setPayloads(loaded);
      } catch (e) {
        if (!disposed) setError((e as Error).message);
      } finally {
        signalReady();
      }
    })();
    return () => {
      disposed = true;
    };
  }, []);

  const all = useMemo<Entry[]>(
    () => (index ? Object.entries(index).sort(([, a], [, b]) => b.lat - a.lat) : []),
    [index]
  );

  if (error) {
    return (
      <main class="page">
        <AppHeader right={<span class="head-note">spots</span>} />
        <p class="state">{error}</p>
      </main>
    );
  }

  const q = query.trim().toLowerCase();
  const match = ([id, e]: Entry) =>
    !q ||
    e.name.toLowerCase().includes(q) ||
    (e.region ?? "").toLowerCase().includes(q) ||
    id.includes(q);

  const favRows = all.filter(([id]) => favs.includes(id)).filter(match);
  let nearRows = all.filter(([id]) => !favs.includes(id)).filter(match);
  if (pos) {
    nearRows = [...nearRows].sort(
      ([, a], [, b]) =>
        distanceKm(pos, { lat: a.lat, lon: a.lon }) - distanceKm(pos, { lat: b.lat, lon: b.lon })
    );
  }
  // Initial state (no search text) shows only the closest handful; typing reveals all matches.
  if (!q) nearRows = nearRows.slice(0, NEARBY_LIMIT);

  // Map areas: regions whose name matches the query (only while searching).
  const regionMatches = q && index ? regionsFrom(index).filter((r) => r.name.toLowerCase().includes(q)) : [];
  const noResults = regionMatches.length === 0 && favRows.length === 0 && nearRows.length === 0;

  return (
    <main class="page">
      <AppHeader right={<span class="head-note">spots</span>} />
      {!index ? (
        <p class="state">Loading…</p>
      ) : (
        <div class="spots-page">
          <div class="search-box">
            <SearchIcon size={16} />
            <input
              placeholder="Search spots or regions"
              aria-label="Search spots or regions"
              value={query}
              onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
            />
          </div>
          {regionMatches.length > 0 && (
            <div>
              <span class="eyebrow">Map areas</span>
              <div class="spot-group-list">
                {regionMatches.map((r) => (
                  <RegionRow key={r.name} region={r} />
                ))}
              </div>
            </div>
          )}
          {favRows.length > 0 && (
            <div>
              <span class="eyebrow">Favorites</span>
              {groupByRegion(favRows).map(([region, rows]) => (
                <div key={region} class="fav-region">
                  <span class="fav-region-head">{region}</span>
                  <div class="rank-list">
                    {rows.map(([id, e]) => {
                      const p = payloads[id];
                      return p ? (
                        <SpotCard
                          key={id}
                          data={p}
                          date={p.days[0]?.date ?? ""}
                          km={pos ? distanceKm(pos, { lat: e.lat, lon: e.lon }) : undefined}
                          isFav
                          onToggle={() => onToggle(id)}
                        />
                      ) : (
                        <Row key={id} id={id} entry={e} payload={undefined} isFav onToggle={() => onToggle(id)} />
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div>
            {nearRows.length > 0 && <span class="eyebrow">{q ? "Spots" : "Nearby"}</span>}
            <div class="spot-group-list">
              {nearRows.map(([id, e]) => (
                <Row
                  key={id}
                  id={id}
                  entry={e}
                  payload={payloads[id]}
                  isFav={false}
                  onToggle={() => onToggle(id)}
                />
              ))}
              {noResults && <p class="search-empty">No spots or regions match “{query}”.</p>}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
