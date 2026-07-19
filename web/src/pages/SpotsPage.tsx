import { useEffect, useMemo, useState } from "preact/hooks";
import { fetchIndex, fetchSpot } from "../api";
import { SearchIcon, StarIcon } from "../components/icons";
import { AppHeader, SpotTitle, TierDot } from "../components/parts";
import { ratingWord } from "../conditions";
import { getFavorites } from "../favorites";
import { bestWindow, dateOf, splitName, windLabel } from "../format";
import { distanceKm, getPosition, type LatLon } from "../geo";
import { fmtH, fmtRange, heightUnit, useUnits, type Units } from "../units";
import type { IndexEntry, SpotPayload } from "../types";

type Entry = [string, IndexEntry];

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
}: {
  id: string;
  entry: IndexEntry;
  payload: SpotPayload | undefined;
  isFav: boolean;
}) {
  const units = useUnits();
  const { name, region } = splitName(entry.name);
  return (
    <button class="spot-row-card" onClick={() => (location.hash = `#/spot/${id}`)}>
      <TierDot bucket={entry.bucket} />
      <span class="mid">
        <SpotTitle name={name} region={region} />
        <span class="line tabular">
          {payload ? payloadLine(payload, units) : `${fmtRange(entry.h, units)} · ${ratingWord(entry.bucket)}`}
        </span>
      </span>
      <span
        class={`star-btn${isFav ? " on" : ""}`}
        style="width:auto;height:auto"
        aria-hidden="true"
      >
        <StarIcon size={16} />
      </span>
    </button>
  );
}

export function SpotsPage() {
  const [index, setIndex] = useState<Record<string, IndexEntry> | null>(null);
  const [payloads, setPayloads] = useState<Record<string, SpotPayload>>({});
  const [error, setError] = useState<string | null>(null);
  const [pos, setPos] = useState<LatLon | null>(null);
  const [query, setQuery] = useState("");
  const favs = getFavorites();

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
  const match = ([id, e]: Entry) => !q || e.name.toLowerCase().includes(q) || id.includes(q);

  const favRows = all.filter(([id]) => favs.includes(id)).filter(match);
  let nearRows = all.filter(([id]) => !favs.includes(id)).filter(match);
  if (pos) {
    nearRows = [...nearRows].sort(
      ([, a], [, b]) =>
        distanceKm(pos, { lat: a.lat, lon: a.lon }) - distanceKm(pos, { lat: b.lat, lon: b.lon })
    );
  }

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
              placeholder="Search spots"
              aria-label="Search spots"
              value={query}
              onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
            />
          </div>
          {favRows.length > 0 && (
            <div>
              <span class="eyebrow">Favorites</span>
              <div class="spot-group-list">
                {favRows.map(([id, e]) => (
                  <Row key={id} id={id} entry={e} payload={payloads[id]} isFav />
                ))}
              </div>
            </div>
          )}
          <div>
            <span class="eyebrow">Nearby</span>
            <div class="spot-group-list">
              {nearRows.map(([id, e]) => (
                <Row key={id} id={id} entry={e} payload={payloads[id]} isFav={false} />
              ))}
              {nearRows.length === 0 && <p class="search-empty">No spots match “{query}”.</p>}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
