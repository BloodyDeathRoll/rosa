import { useEffect, useState } from "preact/hooks";
import { fetchIndex, fetchSpot } from "../api";
import { SearchIcon, ShirtIcon, ThermometerIcon, WavesIcon } from "../components/icons";
import { AppHeader, Pill, Spark, SpotTitle, StarButton } from "../components/parts";
import { getFavorites, toggleFavorite } from "../favorites";
import { bestWindow, cardinal, dateOf, splitName, windLabel } from "../format";
import { distanceKm, getPosition } from "../geo";
import { getRecents } from "../recents";
import { fmtH, fmtTemp, heightUnit, useUnits } from "../units";
import type { SpotPayload } from "../types";

const NEAR_RADIUS_KM = 50;

function todayHours(data: SpotPayload) {
  return data.hours.filter((h) => dateOf(h.t) === dateOf(data.hours[0]?.t ?? ""));
}

/** Rich card for the last spot the user opened. */
function DetailCard({ data }: { data: SpotPayload }) {
  const units = useUnits();
  const cur = data.current;
  const { name, region } = splitName(data.spot.name);
  const swell = cur.swells.find((s) => s.in_window) ?? cur.swells[0];
  const hrs = todayHours(data);
  const bw = bestWindow(hrs);
  return (
    <button class="detail-card" onClick={() => (location.hash = `#/spot/${data.spot.id}`)}>
      <span class="top">
        <SpotTitle name={name} region={region} />
        <Pill bucket={cur.bucket} />
      </span>
      <span class="line tabular">
        {fmtH(cur.h_mid, units)} {heightUnit(units)} · {windLabel(cur)}
        {swell ? ` · ${Math.round(swell.period)} s ${cardinal(swell.dir)}` : ""}
      </span>
      <Spark hours={hrs} bucket={cur.bucket} w={326} h={36} stretch />
      <span class="temps-row">
        <span>
          <ThermometerIcon />
          <span class="tabular">air {cur.air !== null ? fmtTemp(cur.air, units) : "—"}</span>
        </span>
        <span>
          <WavesIcon />
          <span class="tabular">water {cur.sst !== null ? fmtTemp(cur.sst, units) : "—"}</span>
        </span>
        {cur.wetsuit && (
          <span>
            <ShirtIcon />
            <span class="suit">{cur.wetsuit}</span>
          </span>
        )}
      </span>
      <span class="foot">
        <span class="window">
          Best window <b>{bw ? `${bw.start}–${bw.end}` : "none today"}</b>
        </span>
        <span class="accent-link">Open forecast →</span>
      </span>
    </button>
  );
}

function SpotCard({
  data,
  km,
  isFav,
  onToggle,
}: {
  data: SpotPayload;
  km: number | undefined;
  isFav: boolean;
  onToggle: () => void;
}) {
  const units = useUnits();
  const cur = data.current;
  const { name, region } = splitName(data.spot.name);
  return (
    <div class="rank-card">
      <StarButton on={isFav} name={name} onToggle={onToggle} />
      <button class="open" onClick={() => (location.hash = `#/spot/${data.spot.id}`)}>
        <SpotTitle name={name} region={region} />
        <span class="line tabular">
          {fmtH(cur.h_mid, units)} {heightUnit(units)} · {windLabel(cur)}
        </span>
        <Spark hours={todayHours(data)} bucket={cur.bucket} />
      </button>
      <div class="side">
        <Pill bucket={cur.bucket} />
        {km !== undefined && <span class="rank-n tabular">{Math.round(km)} km</span>}
      </div>
    </div>
  );
}

export function TodayPage() {
  const [detail, setDetail] = useState<SpotPayload | null>(null);
  const [cards, setCards] = useState<SpotPayload[] | null>(null);
  const [dists, setDists] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>(getFavorites);

  useEffect(() => {
    let disposed = false;
    (async () => {
      try {
        const [index, pos] = await Promise.all([fetchIndex(), getPosition()]);
        if (disposed) return;
        const entries = Object.entries(index.spots);
        const lastId = getRecents()[0];
        const km: Record<string, number> = {};
        if (pos) for (const [id, e] of entries) km[id] = distanceKm(pos, { lat: e.lat, lon: e.lon });
        setDists(km);
        // nearest spots within 50 km, closest first; full list north→south
        // when location is denied or nothing is in range
        const near = pos
          ? entries
              .filter(([id]) => (km[id] ?? Infinity) <= NEAR_RADIUS_KM)
              .sort(([a], [b]) => (km[a] ?? 0) - (km[b] ?? 0))
          : [];
        const pool = near.length > 0 ? near : [...entries].sort(([, a], [, b]) => b.lat - a.lat);
        const listIds = pool.map(([id]) => id).filter((id) => id !== lastId);
        const wantDetail = lastId !== undefined && index.spots[lastId] !== undefined;
        const results = await Promise.allSettled([
          ...(wantDetail ? [fetchSpot(lastId)] : []),
          ...listIds.map(fetchSpot),
        ]);
        if (disposed) return;
        const loaded = results
          .filter((r): r is PromiseFulfilledResult<SpotPayload> => r.status === "fulfilled")
          .map((r) => r.value);
        setDetail(wantDetail ? (loaded.find((d) => d.spot.id === lastId) ?? null) : null);
        setCards(loaded.filter((d) => d.spot.id !== lastId));
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
        <div class="rank-list" style="flex:1">
          {detail && <DetailCard data={detail} />}
          {cards.map((d) => (
            <SpotCard
              key={d.spot.id}
              data={d}
              km={dists[d.spot.id]}
              isFav={favs.includes(d.spot.id)}
              onToggle={() => setFavs(toggleFavorite(d.spot.id))}
            />
          ))}
        </div>
      )}
    </main>
  );
}
