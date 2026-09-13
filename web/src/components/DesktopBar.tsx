import { useEffect, useMemo, useState } from "preact/hooks";
import { fetchIndex } from "../api";
import { ratingVar } from "../conditions";
import { useFavorites } from "../favorites";
import { splitName } from "../format";
import { ACCOUNT_EVENT, profile, type Profile } from "../session";
import { TAB_ROUTES, type Tab } from "../tabs";
import { fmtRange, useUnits } from "../units";
import type { IndexEntry } from "../types";
import { SearchIcon, UserIcon } from "./icons";
import { ShareButton } from "./parts";

const NAV: { tab: Tab; label: string }[] = [
  { tab: "today", label: "Today" },
  { tab: "spots", label: "Spots" },
  { tab: "map", label: "Map" },
  { tab: "charts", label: "Charts" },
];

/** Wide-screen chrome (styles.css DESKTOP block; `display: none` on phones):
    brand, the four sections as text links, a search field, share and the
    account avatar on one row, and under it a ticker of your favorites - name, today's
    range, tier dot - so a glance at any page answers "where?" before a click.
    Profile has no link of its own: the avatar is the way in, as on Surfline. */
export function DesktopBar({ active }: { active: Tab | null }) {
  const [index, setIndex] = useState<Record<string, IndexEntry> | null>(null);
  const [who, setWho] = useState<Profile | null>(profile);
  const [favs] = useFavorites();
  const units = useUnits();

  useEffect(() => {
    let disposed = false;
    fetchIndex().then(
      (idx) => {
        if (!disposed) setIndex(idx.spots);
      },
      () => undefined
    );
    const onAccount = () => setWho(profile());
    addEventListener(ACCOUNT_EVENT, onAccount);
    return () => {
      disposed = true;
      removeEventListener(ACCOUNT_EVENT, onAccount);
    };
  }, []);

  // north to south, the app's order for any list of spots
  const ticker = useMemo(
    () =>
      index
        ? favs
            .filter((id) => index[id])
            .map((id) => [id, index[id]!] as const)
            .sort(([, a], [, b]) => b.lat - a.lat)
        : [],
    [index, favs]
  );

  return (
    <header class="desk-bar">
      <div class="desk-bar-row">
        <a class="brand" href="/" aria-label="Rosa home">
          <span class="brand-mark" role="img" aria-label="Rosa" />
          <span class="brand-word">
            rosa<span class="brand-dot" aria-hidden="true" />
          </span>
        </a>
        <nav class="desk-nav" aria-label="Main">
          {NAV.map(({ tab, label }) => (
            <a
              key={tab}
              href={TAB_ROUTES[tab]}
              class={active === tab ? "on" : ""}
              aria-current={active === tab ? "page" : undefined}
            >
              {label}
            </a>
          ))}
        </nav>
        <a class="desk-search" href="/search">
          <SearchIcon size={16} />
          <span>Search spots or regions</span>
        </a>
        <ShareButton class="desk-share" />
        <a
          class={`desk-account${active === "settings" ? " on" : ""}`}
          href={TAB_ROUTES.settings}
          aria-label="Profile"
          aria-current={active === "settings" ? "page" : undefined}
        >
          {who?.picture ? (
            <img src={who.picture} alt="" width="36" height="36" referrerpolicy="no-referrer" />
          ) : (
            <UserIcon size={20} />
          )}
        </a>
      </div>
      {ticker.length > 0 && (
        <div class="desk-ticker">
          <div class="desk-ticker-row">
            <span class="desk-ticker-label">Your spots</span>
            {ticker.map(([id, e]) => (
              <a key={id} class="desk-tick" href={`/spot/${id}`}>
                <i style={`background:${ratingVar(e.bucket)}`} aria-hidden="true" />
                <span>{splitName(e.name).name}</span>
                <b class="tabular">{fmtRange(e.h, units)}</b>
              </a>
            ))}
          </div>
        </div>
      )}
    </header>
  );
}
