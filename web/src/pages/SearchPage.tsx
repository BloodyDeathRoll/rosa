import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { fetchIndex } from "../api";
import {
  CamIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  MapPinIcon,
  SearchIcon,
} from "../components/icons";
import { SpotTitle, StarButton, TierDot } from "../components/parts";
import { ratingWord } from "../conditions";
import { useFavorites } from "../favorites";
import { splitName } from "../format";
import { getRecents } from "../recents";
import { regionsFrom, type RegionInfo } from "../regions";
import { signalReady } from "../splash";
import { fmtRange, useUnits } from "../units";
import type { IndexEntry } from "../types";
import { setPendingArea } from "./MapPage";

type Entry = [string, IndexEntry];

/** A spot result / recent row (card-less) → opens the spot page; the star on the
    right toggles favorites in place without navigating. */
export function ResultRow({
  id,
  entry,
  isFav,
  onToggle,
}: {
  id: string;
  entry: IndexEntry;
  isFav: boolean;
  onToggle: () => void;
}) {
  const units = useUnits();
  const { name, region } = splitName(entry.name);
  // A break's town is what half of them are actually famous under, and it is why a row
  // matched a search for it - so it stands in as the subtitle when the name carries none.
  const sub = region ?? entry.town ?? null;
  return (
    <a class="spot-row-card plain" href={`/spot/${id}`}>
      <TierDot bucket={entry.bucket} />
      <span class="mid">
        <SpotTitle name={name} region={sub} />
        <span class="line tabular">
          {fmtRange(entry.h, units)} · {ratingWord(entry.bucket)}
        </span>
      </span>
      <span class="card-side">
        {(entry.cams?.length ?? (entry.cam ? 1 : 0)) > 0 && (
          <span class="cam-mark" title="Live cam">
            <CamIcon />
          </span>
        )}
        <StarButton on={isFav} name={name} size={16} onToggle={onToggle} />
      </span>
    </a>
  );
}

/** A matched "map area" → frames the whole region on the Map tab. */
function RegionRow({ region }: { region: RegionInfo }) {
  return (
    <a class="spot-row-card plain area-row" href="/map" onClick={() => setPendingArea(region.name)}>
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

/** Focused search screen (reached via the header search icon on Home or Spots):
    an open, autofocused search field over the user's recently-visited spots;
    typing reveals matching spots + map areas. */
export function SearchPage() {
  const [index, setIndex] = useState<Record<string, IndexEntry> | null>(null);
  const [query, setQuery] = useState("");
  const [favs, onToggle] = useFavorites();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let disposed = false;
    (async () => {
      try {
        const idx = await fetchIndex();
        if (!disposed) setIndex(idx.spots);
      } finally {
        signalReady();
      }
    })();
    return () => {
      disposed = true;
    };
  }, []);

  // open with the keyboard ready
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const all = useMemo<Entry[]>(
    () => (index ? Object.entries(index).sort(([, a], [, b]) => b.lat - a.lat) : []),
    [index]
  );
  // last spots the user visited (pushRecent fires on every spot page open)
  const recents = useMemo<Entry[]>(() => {
    if (!index) return [];
    return getRecents()
      .map((id) => (index[id] ? ([id, index[id]] as Entry) : null))
      .filter((x): x is Entry => x !== null);
  }, [index]);

  const q = query.trim().toLowerCase();
  const match = ([id, e]: Entry) =>
    e.name.toLowerCase().includes(q) ||
    (e.region ?? "").toLowerCase().includes(q) ||
    (e.town ?? "").toLowerCase().includes(q) ||
    id.includes(q);
  const spotMatches = q ? all.filter(match) : [];
  const regionMatches =
    q && index ? regionsFrom(index).filter((r) => r.name.toLowerCase().includes(q)) : [];
  const noResults = Boolean(q) && spotMatches.length === 0 && regionMatches.length === 0;

  return (
    <main class="page">
      <header class="search-head">
        <button class="spot-back" onClick={() => history.back()} aria-label="Back">
          <ChevronLeftIcon />
        </button>
        <div class="search-box grow">
          <SearchIcon size={16} stroke={1.5} />
          <input
            ref={inputRef}
            placeholder="Search spots or regions"
            aria-label="Search spots or regions"
            value={query}
            onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
          />
        </div>
      </header>
      {!index ? (
        <p class="state">Loading…</p>
      ) : (
        <div class="spots-page">
          {!q ? (
            recents.length > 0 ? (
              <div>
                <span class="eyebrow">Recent</span>
                <div class="spot-group-list">
                  {recents.map(([id, e]) => (
                    <ResultRow key={id} id={id} entry={e} isFav={favs.includes(id)} onToggle={() => onToggle(id)} />
                  ))}
                </div>
              </div>
            ) : (
              <p class="search-empty">Search for a spot or region.</p>
            )
          ) : (
            <>
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
              {spotMatches.length > 0 && (
                <div>
                  <span class="eyebrow">Spots</span>
                  <div class="spot-group-list">
                    {spotMatches.map(([id, e]) => (
                      <ResultRow key={id} id={id} entry={e} isFav={favs.includes(id)} onToggle={() => onToggle(id)} />
                    ))}
                  </div>
                </div>
              )}
              {noResults && <p class="search-empty">No spots or regions match “{query}”.</p>}
            </>
          )}
        </div>
      )}
    </main>
  );
}
