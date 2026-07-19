import { useEffect, useState } from "preact/hooks";
import { fetchIndex } from "../api";
import { AppHeader } from "../components/AppHeader";
import { RatingChip } from "../components/parts";
import { getFavorites, toggleFavorite } from "../favorites";
import { fmtRange, useUnits } from "../units";
import type { SpotIndex } from "../types";
import type { Theme } from "../theme";

export function FavoritesPage({
  theme,
  onToggleTheme,
}: {
  theme: Theme;
  onToggleTheme: () => void;
}) {
  const [index, setIndex] = useState<SpotIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>(getFavorites);
  const units = useUnits();

  useEffect(() => {
    fetchIndex().then(setIndex, (e: Error) => setError(e.message));
  }, []);

  if (error) return <main class="page"><p class="state">{error}</p></main>;
  if (!index) return <main class="page"><p class="state">Loading…</p></main>;

  const rows = favs
    .map((id) => [id, index.spots[id]] as const)
    .filter((x): x is [string, SpotIndex["spots"][string]] => x[1] !== undefined)
    .sort(([, a], [, b]) => b.lat - a.lat);

  return (
    <main class="page">
      <AppHeader theme={theme} onToggleTheme={onToggleTheme} />
      <h2 class="list-title">Favorites</h2>
      {rows.length === 0 ? (
        <p class="state">
          No favorites yet. Star a spot — from search, the home list, or its page — and it
          lives here.
        </p>
      ) : (
        <ul class="spots">
          {rows.map(([id, e]) => (
            <li class="spot-row" key={id}>
              <button
                class="star"
                aria-pressed
                aria-label={`Remove ${e.name} from favorites`}
                onClick={() => setFavs(toggleFavorite(id))}
              >
                ★
              </button>
              <a href={`#/spot/${id}`}>
                <span class="spot-name">{e.name}</span>
                <span class="spot-now">
                  <b>{fmtRange(e.h, units)}</b>
                  <RatingChip bucket={e.bucket} />
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
