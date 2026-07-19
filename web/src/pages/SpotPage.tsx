import { useEffect, useState } from "preact/hooks";
import { fetchSpot } from "../api";
import { CurrentCard } from "../components/CurrentCard";
import { ForecastTable } from "../components/ForecastTable";
import { BackIcon, MoonIcon, SunIcon } from "../components/icons";
import { getFavorites, toggleFavorite } from "../favorites";
import { pushRecent } from "../recents";
import type { SpotPayload } from "../types";
import type { Theme } from "../theme";

export function SpotPage({
  id,
  theme,
  onToggleTheme,
}: {
  id: string;
  theme: Theme;
  onToggleTheme: () => void;
}) {
  const [data, setData] = useState<SpotPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>(getFavorites);

  useEffect(() => {
    setData(null);
    setError(null);
    pushRecent(id);
    fetchSpot(id).then(setData, (e: Error) => setError(e.message));
  }, [id]);

  const head = (
    <header class="spot-head">
      <a class="icon-btn" href="#/" aria-label="Back to spots">
        <BackIcon />
      </a>
      <span class="head-actions">
        <button
          class="icon-btn"
          onClick={onToggleTheme}
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
        </button>
        <button
          class="star"
          aria-pressed={favs.includes(id)}
          aria-label={favs.includes(id) ? "Remove from favorites" : "Add to favorites"}
          onClick={() => setFavs(toggleFavorite(id))}
        >
          {favs.includes(id) ? "★" : "☆"}
        </button>
      </span>
    </header>
  );

  if (error) {
    return (
      <main class="page">
        {head}
        <p class="state">{error}</p>
      </main>
    );
  }
  if (!data) {
    return (
      <main class="page">
        {head}
        <p class="state">Loading…</p>
      </main>
    );
  }

  return (
    <main class="page">
      {head}
      <CurrentCard name={data.spot.name} cur={data.current} />
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
