import { useEffect, useState } from "preact/hooks";
import { fetchIndex, fetchSpot } from "../api";
import { SearchIcon } from "../components/icons";
import { AppHeader, Pill, Spark, SpotTitle, StarButton } from "../components/parts";
import { getFavorites, toggleFavorite } from "../favorites";
import { dateOf, splitName, windLabel } from "../format";
import { distanceKm, getPosition } from "../geo";
import { fmtH, heightUnit, useUnits } from "../units";
import type { SpotPayload } from "../types";

const NEAR_RADIUS_KM = 50;

function estClock(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

function RankCard({
  data,
  rank,
  isFav,
  onToggle,
}: {
  data: SpotPayload;
  rank: number;
  isFav: boolean;
  onToggle: () => void;
}) {
  const units = useUnits();
  const cur = data.current;
  const { name, region } = splitName(data.spot.name);
  const today = data.hours.filter((h) => dateOf(h.t) === dateOf(data.hours[0]?.t ?? ""));
  return (
    <div class="rank-card">
      <StarButton on={isFav} name={name} onToggle={onToggle} />
      <button class="open" onClick={() => (location.hash = `#/spot/${data.spot.id}`)}>
        <SpotTitle name={name} region={region} />
        <span class="line tabular">
          {fmtH(cur.h_mid, units)} {heightUnit(units)} · {windLabel(cur)}
        </span>
        <Spark hours={today} bucket={cur.bucket} />
      </button>
      <div class="side">
        <Pill bucket={cur.bucket} />
        <span class="rank-n tabular">#{rank}</span>
      </div>
    </div>
  );
}

export function TodayPage() {
  const [cards, setCards] = useState<SpotPayload[] | null>(null);
  const [estAt, setEstAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>(getFavorites);

  useEffect(() => {
    let disposed = false;
    (async () => {
      try {
        const [index, pos] = await Promise.all([fetchIndex(), getPosition()]);
        if (disposed) return;
        const entries = Object.entries(index.spots);
        // "your coast": within 50 km when located, the whole region otherwise
        const near = pos
          ? entries.filter(([, e]) => distanceKm(pos, { lat: e.lat, lon: e.lon }) <= NEAR_RADIUS_KM)
          : [];
        const pool = near.length > 0 ? near : entries;
        // every spot on the coast, ranked — the cards' wind + spark lines
        // come from the (small, CDN-cached) per-spot payloads
        const ranked = pool.sort(([, a], [, b]) => b.rating - a.rating || b.h[1] - a.h[1]);
        setEstAt(ranked[0]?.[1].generated_at ?? null);
        const results = await Promise.allSettled(ranked.map(([id]) => fetchSpot(id)));
        if (disposed) return;
        setCards(
          results
            .filter((r): r is PromiseFulfilledResult<SpotPayload> => r.status === "fulfilled")
            .map((r) => r.value)
        );
      } catch (e) {
        if (!disposed) setError((e as Error).message);
      }
    })();
    return () => {
      disposed = true;
    };
  }, []);

  return (
    <main class="page">
      <AppHeader
        right={
          <a class="icon-btn" href="#/spots" aria-label="Search spots">
            <SearchIcon />
          </a>
        }
      />
      {error ? (
        <p class="state">{error}</p>
      ) : !cards ? (
        <p class="state">Loading…</p>
      ) : (
        <div style="flex:1">
          <div class="rank-head">
            <span class="eyebrow">Your coast, ranked</span>
            {estAt && <span class="est-note tabular">estimated · {estClock(estAt)}</span>}
          </div>
          <div class="rank-list">
            {cards.map((d, i) => (
              <RankCard
                key={d.spot.id}
                data={d}
                rank={i + 1}
                isFav={favs.includes(d.spot.id)}
                onToggle={() => setFavs(toggleFavorite(d.spot.id))}
              />
            ))}
          </div>
        </div>
      )}
    </main>
  );
}
