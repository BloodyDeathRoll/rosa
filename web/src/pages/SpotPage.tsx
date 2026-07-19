import { useEffect, useState } from "preact/hooks";
import { fetchSpot } from "../api";
import { CurrentCard } from "../components/CurrentCard";
import { ForecastTable } from "../components/ForecastTable";
import { getFavorites, toggleFavorite } from "../favorites";
import type { SpotPayload } from "../types";

export function SpotPage({ id }: { id: string }) {
  const [data, setData] = useState<SpotPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>(getFavorites);

  useEffect(() => {
    setData(null);
    setError(null);
    fetchSpot(id).then(setData, (e: Error) => setError(e.message));
  }, [id]);

  if (error) {
    return (
      <main class="page">
        <a class="back" href="#/">← Spots</a>
        <p class="state">{error}</p>
      </main>
    );
  }
  if (!data) {
    return (
      <main class="page">
        <a class="back" href="#/">← Spots</a>
        <p class="state">Loading…</p>
      </main>
    );
  }

  const isFav = favs.includes(id);
  return (
    <main class="page">
      <header class="spot-head">
        <a class="back" href="#/">← Spots</a>
        <h1>{data.spot.name}</h1>
        <button
          class="star"
          aria-pressed={isFav}
          aria-label={isFav ? "Remove from favorites" : "Add to favorites"}
          onClick={() => setFavs(toggleFavorite(id))}
        >
          {isFav ? "★" : "☆"}
        </button>
      </header>
      <CurrentCard cur={data.current} />
      <ForecastTable hours={data.hours} days={data.days} />
      <footer class="meta">
        <p>
          {data.model} · run {data.fetched_at.slice(0, 16).replace("T", " ")} UTC
        </p>
        <p>{data.attribution}</p>
      </footer>
    </main>
  );
}
