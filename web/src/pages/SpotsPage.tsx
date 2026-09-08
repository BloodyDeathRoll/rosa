import { Fragment } from "preact";
import { useEffect, useMemo, useState } from "preact/hooks";
import { fetchIndex, fetchSpot } from "../api";
import {
  GroupChips,
  groupNameOf,
  groupsOf,
  saveGroup,
  savedGroup,
  sectionsOf,
  ALL_GROUP,
} from "../components/GroupChips";
import { SearchIcon } from "../components/icons";
import { AppHeader, SpotTitle, StarButton, TierDot } from "../components/parts";
import { SpotCard } from "../components/SpotCard";
import { ratingWord } from "../conditions";
import { GoogleButton } from "../components/GoogleButton";
import { useFavorites } from "../favorites";
import { signedIn } from "../session";
import { signalReady } from "../splash";
import { bestWindow, dateOf, splitName, todayIn, windLabel } from "../format";
import { fmtH, fmtRange, heightUnit, useUnits, type Units } from "../units";
import type { IndexEntry, SpotPayload } from "../types";

type Entry = [string, IndexEntry];

function payloadLine(data: SpotPayload, units: Units): string {
  const cur = data.current;
  const today = data.hours.filter((h) => dateOf(h.t) === dateOf(data.hours[0]?.t ?? ""));
  const bw = bestWindow(today);
  return `${fmtH(cur.h_mid, units)} ${heightUnit(units)} · ${windLabel(cur)} · best ${bw ? bw.start : "-"}`;
}

/** Fallback row while a favorite's full payload is still loading. */
function Row({
  id,
  entry,
  payload,
  onToggle,
}: {
  id: string;
  entry: IndexEntry;
  payload: SpotPayload | undefined;
  onToggle: () => void;
}) {
  const units = useUnits();
  const { name, region } = splitName(entry.name);
  return (
    <a class="spot-row-card" href={`#/spot/${id}`}>
      <TierDot bucket={entry.bucket} />
      <span class="mid">
        <SpotTitle name={name} region={region} />
        <span class="line tabular">
          {payload ? payloadLine(payload, units) : `${fmtRange(entry.h, units)} · ${ratingWord(entry.bucket)}`}
        </span>
      </span>
      <StarButton on name={name} size={16} onToggle={onToggle} />
    </a>
  );
}

/** Spots tab = saved favorites, filtered by a Surfline-style region group bar
    ("All" + one chip per region present in your favorites). */
export function SpotsPage() {
  const [index, setIndex] = useState<Record<string, IndexEntry> | null>(null);
  const [payloads, setPayloads] = useState<Record<string, SpotPayload>>({});
  const [error, setError] = useState<string | null>(null);
  const [favs, onToggle] = useFavorites();
  // the chip survives a relaunch; if that region is no longer among your
  // favourites, `activeGroup` below falls back to All.
  const [group, setGroup] = useState<string>(savedGroup);

  useEffect(() => {
    let disposed = false;
    (async () => {
      try {
        const idx = await fetchIndex();
        if (disposed) return;
        setIndex(idx.spots);
      } catch (e) {
        if (!disposed) setError((e as Error).message);
        signalReady();
      }
    })();
    return () => {
      disposed = true;
    };
  }, []);

  // Payloads follow the list: the first pass loads every favorite, and a later
  // change (a sign-in merge, a sync from another device) loads only what is new.
  useEffect(() => {
    if (!index) return;
    const missing = favs.filter((id) => index[id] && !payloads[id]);
    if (missing.length === 0) {
      signalReady();
      return;
    }
    let disposed = false;
    (async () => {
      const results = await Promise.allSettled(missing.map(fetchSpot));
      if (disposed) return;
      const loaded: Record<string, SpotPayload> = {};
      for (const r of results) if (r.status === "fulfilled") loaded[r.value.spot.id] = r.value;
      setPayloads((prev) => ({ ...prev, ...loaded }));
      signalReady();
    })();
    return () => {
      disposed = true;
    };
    // payloads is read, not a trigger: a fetch result must not start another round
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, favs]);

  const search = (
    <a class="icon-btn" href="#/search" aria-label="Search spots">
      <SearchIcon />
    </a>
  );

  const favRows = useMemo<Entry[]>(
    () =>
      index
        ? Object.entries(index)
            .filter(([id]) => favs.includes(id))
            .sort(([, a], [, b]) => b.lat - a.lat)
        : [],
    [index, favs]
  );
  const groups = groupsOf(favRows);
  const activeGroup = groups.includes(group) ? group : ALL_GROUP;
  const shown =
    activeGroup === ALL_GROUP
      ? favRows
      : favRows.filter(([, e]) => groupNameOf(e.region) === activeGroup);

  if (error) {
    return (
      <main class="page">
        <AppHeader right={search} title="Your spots" />
        <p class="state">{error}</p>
      </main>
    );
  }

  return (
    <main class="page">
      <AppHeader right={search} title="Your spots" />
      {!index ? (
        <p class="state">Loading…</p>
      ) : favRows.length === 0 ? (
        signedIn() ? (
          <p class="empty-center">No favorites yet</p>
        ) : (
          <div class="empty-center empty-signin">
            <p>Sign in to save spots</p>
            <GoogleButton size="large" width={260} />
          </div>
        )
      ) : (
        <div class="spots-page">
          {groups.length > 1 && (
            <GroupChips
              groups={groups}
              selected={activeGroup}
              onSelect={(g) => {
                setGroup(g);
                saveGroup(g);
              }}
            />
          )}
          <div class="rank-list">
            {sectionsOf(shown, ([, e]) => e.region).map(({ group, rows }) => (
              <Fragment key={group}>
                {/* Only under "All" - inside a filtered group every row is that
                    group, so the heading would just repeat the selected chip. */}
                {activeGroup === ALL_GROUP && groups.length > 2 && (
                  <h3 class="group-label">{group}</h3>
                )}
                {rows.map(([id, e]) => {
                  const p = payloads[id];
                  return p ? (
                    <SpotCard
                      key={id}
                      data={p}
                      date={todayIn(p.spot.timezone)}
                      isFav
                      onToggle={() => onToggle(id)}
                    />
                  ) : (
                    <Row
                      key={id}
                      id={id}
                      entry={e}
                      payload={undefined}
                      onToggle={() => onToggle(id)}
                    />
                  );
                })}
              </Fragment>
            ))}
          </div>
        </div>
      )}
    </main>
  );
}
