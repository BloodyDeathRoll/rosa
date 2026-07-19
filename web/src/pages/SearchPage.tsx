import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { fetchIndex } from "../api";
import { BackIcon } from "../components/icons";
import { getFavorites, toggleFavorite } from "../favorites";
import { distanceKm, getPosition, type LatLon } from "../geo";
import { getRecents } from "../recents";
import type { SpotIndex } from "../types";

type Entry = [string, SpotIndex["spots"][string]];

function ResultRow({
  id,
  name,
  km,
  isFav,
  onToggle,
}: {
  id: string;
  name: string;
  km?: number;
  isFav: boolean;
  onToggle: (id: string) => void;
}) {
  return (
    <li class="result-row">
      <a href={`#/spot/${id}`}>
        <span>
          {name}
          {km !== undefined && <small>{Math.round(km)} km</small>}
        </span>
      </a>
      <button
        class="star"
        aria-pressed={isFav}
        aria-label={isFav ? `Remove ${name} from favorites` : `Add ${name} to favorites`}
        onClick={() => onToggle(id)}
      >
        {isFav ? "★" : "＋"}
      </button>
    </li>
  );
}

export function SearchPage() {
  const [index, setIndex] = useState<SpotIndex | null>(null);
  const [query, setQuery] = useState("");
  const [favs, setFavs] = useState<string[]>(getFavorites);
  const [pos, setPos] = useState<LatLon | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void fetchIndex().then(setIndex, () => setIndex(null));
    void getPosition().then(setPos);
    inputRef.current?.focus();
  }, []);

  const onToggle = (id: string) => setFavs(toggleFavorite(id));

  const all = useMemo<Entry[]>(
    () => (index ? Object.entries(index.spots).sort(([, a], [, b]) => b.lat - a.lat) : []),
    [index]
  );
  const km = (e: Entry[1]) => (pos ? distanceKm(pos, { lat: e.lat, lon: e.lon }) : undefined);

  const q = query.trim().toLowerCase();
  const matches = q
    ? all.filter(([id, e]) => e.name.toLowerCase().includes(q) || id.includes(q))
    : null;

  const recents = getRecents()
    .map((id) => all.find(([aid]) => aid === id))
    .filter((x): x is Entry => x !== undefined);

  const nearby = (
    pos ? [...all].sort(([, a], [, b]) => (km(a) ?? 0) - (km(b) ?? 0)) : all
  ).slice(0, 8);

  return (
    <main class="page search-page">
      <header class="search-head">
        <a class="icon-btn" href="#/" aria-label="Back">
          <BackIcon />
        </a>
        <input
          ref={inputRef}
          type="search"
          placeholder="Search by spot or region"
          aria-label="Search by spot or region"
          value={query}
          onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
        />
      </header>

      {matches ? (
        <ul class="results">
          {matches.map(([id, e]) => (
            <ResultRow key={id} id={id} name={e.name} km={km(e)} isFav={favs.includes(id)} onToggle={onToggle} />
          ))}
          {matches.length === 0 && <li class="search-empty">No spots match "{query}" yet</li>}
        </ul>
      ) : (
        <>
          {recents.length > 0 && (
            <>
              <h2 class="list-title">Recents</h2>
              <ul class="results">
                {recents.map(([id, e]) => (
                  <ResultRow key={id} id={id} name={e.name} km={km(e)} isFav={favs.includes(id)} onToggle={onToggle} />
                ))}
              </ul>
            </>
          )}
          <h2 class="list-title">{pos ? "Nearby" : "Spots"}</h2>
          <ul class="results">
            {nearby.map(([id, e]) => (
              <ResultRow key={id} id={id} name={e.name} km={km(e)} isFav={favs.includes(id)} onToggle={onToggle} />
            ))}
          </ul>
        </>
      )}
    </main>
  );
}
