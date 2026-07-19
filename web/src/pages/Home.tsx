import { useEffect, useState } from "preact/hooks";
import { fetchIndex } from "../api";
import { Search } from "../components/Search";
import { RatingChip } from "../components/parts";
import { getFavorites, toggleFavorite } from "../favorites";
import { distanceKm, getPosition, type LatLon } from "../geo";
import { heightRange } from "../format";
import type { SpotIndex } from "../types";
import type { Theme } from "../theme";

type Entry = [string, SpotIndex["spots"][string]];

function SpotRow({
  id,
  entry,
  isFav,
  km,
  onToggle,
}: {
  id: string;
  entry: SpotIndex["spots"][string];
  isFav: boolean;
  km?: number;
  onToggle: (id: string) => void;
}) {
  return (
    <li class="spot-row">
      <button
        class="star"
        aria-pressed={isFav}
        aria-label={isFav ? `Remove ${entry.name} from favorites` : `Add ${entry.name} to favorites`}
        onClick={() => onToggle(id)}
      >
        {isFav ? "★" : "☆"}
      </button>
      <a href={`#/spot/${id}`}>
        <span class="spot-name">
          {entry.name}
          {km !== undefined && <small>{Math.round(km)} km</small>}
        </span>
        <span class="spot-now">
          <b>{heightRange(entry.h)}</b>
          <RatingChip bucket={entry.bucket} rating={entry.rating} />
        </span>
      </a>
    </li>
  );
}

export function Home({ theme, onToggleTheme }: { theme: Theme; onToggleTheme: () => void }) {
  const [index, setIndex] = useState<SpotIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>(getFavorites);
  const [pos, setPos] = useState<LatLon | null>(null);

  useEffect(() => {
    fetchIndex().then(setIndex, (e: Error) => setError(e.message));
    void getPosition().then(setPos);
  }, []);

  const onToggle = (id: string) => setFavs(toggleFavorite(id));

  if (error) return <main class="page"><p class="state">{error}</p></main>;
  if (!index) return <main class="page"><p class="state">Loading…</p></main>;

  // north → south, not alphabetical
  const all: Entry[] = Object.entries(index.spots).sort(([, a], [, b]) => b.lat - a.lat);
  const favRows = all.filter(([id]) => favs.includes(id));
  const near: Entry[] | null = pos
    ? [...all]
        .sort(
          ([, a], [, b]) =>
            distanceKm(pos, { lat: a.lat, lon: a.lon }) -
            distanceKm(pos, { lat: b.lat, lon: b.lon })
        )
        .slice(0, 5)
    : null;

  return (
    <main class="page">
      <header class="home-head">
        <h1>Rosa</h1>
        <button
          class="theme-toggle"
          onClick={onToggleTheme}
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? "☀" : "☾"}
        </button>
      </header>
      <Search index={index} />
      {favRows.length > 0 && (
        <>
          <h2 class="list-title">Favorites</h2>
          <ul class="spots">
            {favRows.map(([id, e]) => (
              <SpotRow
                key={id}
                id={id}
                entry={e}
                isFav
                km={pos ? distanceKm(pos, { lat: e.lat, lon: e.lon }) : undefined}
                onToggle={onToggle}
              />
            ))}
          </ul>
        </>
      )}
      {near && (
        <>
          <h2 class="list-title">Near you</h2>
          <ul class="spots">
            {near.map(([id, e]) => (
              <SpotRow
                key={id}
                id={id}
                entry={e}
                isFav={favs.includes(id)}
                km={pos ? distanceKm(pos, { lat: e.lat, lon: e.lon }) : undefined}
                onToggle={onToggle}
              />
            ))}
          </ul>
        </>
      )}
      <h2 class="list-title">All spots · north to south</h2>
      <ul class="spots">
        {all.map(([id, e]) => (
          <SpotRow
            key={id}
            id={id}
            entry={e}
            isFav={favs.includes(id)}
            km={pos ? distanceKm(pos, { lat: e.lat, lon: e.lon }) : undefined}
            onToggle={onToggle}
          />
        ))}
      </ul>
    </main>
  );
}
