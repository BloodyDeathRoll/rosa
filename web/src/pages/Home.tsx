import { useEffect, useState } from "preact/hooks";
import { fetchIndex } from "../api";
import { RatingChip } from "../components/parts";
import { getFavorites, toggleFavorite } from "../favorites";
import { heightRange } from "../format";
import type { SpotIndex } from "../types";

function SpotRow({
  id,
  entry,
  isFav,
  onToggle,
}: {
  id: string;
  entry: SpotIndex["spots"][string];
  isFav: boolean;
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
        <span class="spot-name">{entry.name}</span>
        <span class="spot-now">
          <b>{heightRange(entry.h)}</b>
          <RatingChip bucket={entry.bucket} rating={entry.rating} />
        </span>
      </a>
    </li>
  );
}

export function Home() {
  const [index, setIndex] = useState<SpotIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>(getFavorites);

  useEffect(() => {
    fetchIndex().then(setIndex, (e: Error) => setError(e.message));
  }, []);

  const onToggle = (id: string) => setFavs(toggleFavorite(id));

  if (error) return <main class="page"><p class="state">{error}</p></main>;
  if (!index) return <main class="page"><p class="state">Loading…</p></main>;

  const all = Object.entries(index.spots).sort(([, a], [, b]) => a.name.localeCompare(b.name));
  const favRows = all.filter(([id]) => favs.includes(id));
  const restRows = all.filter(([id]) => !favs.includes(id));

  return (
    <main class="page">
      <header class="home-head">
        <h1>Rosa</h1>
        <p>Should I surf, when, where?</p>
      </header>
      {favRows.length > 0 && (
        <>
          <h2 class="list-title">Favorites</h2>
          <ul class="spots">
            {favRows.map(([id, e]) => (
              <SpotRow key={id} id={id} entry={e} isFav onToggle={onToggle} />
            ))}
          </ul>
        </>
      )}
      <h2 class="list-title">{favRows.length > 0 ? "All spots" : "Spots — star your locals"}</h2>
      <ul class="spots">
        {restRows.map(([id, e]) => (
          <SpotRow key={id} id={id} entry={e} isFav={false} onToggle={onToggle} />
        ))}
      </ul>
    </main>
  );
}
