import { useEffect, useState } from "preact/hooks";
import { GearIcon, HomeIcon, MapIcon, StarIcon } from "./components/icons";
import { MapPage } from "./pages/MapPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SpotPage } from "./pages/SpotPage";
import { SpotsPage } from "./pages/SpotsPage";
import { TodayPage } from "./pages/TodayPage";
import { applyTheme, initialTheme, saveTheme, type Theme } from "./theme";
import { lastTab, saveLastTab, TAB_ROUTES, type Tab } from "./tabs";

type Route =
  | { page: "today" }
  | { page: "spots" }
  | { page: "map" }
  | { page: "settings" }
  | { page: "spot"; id: string };

function parseRoute(hash: string): Route {
  const spot = /^#\/spot\/([\w-]+)/.exec(hash);
  if (spot?.[1]) return { page: "spot", id: spot[1] };
  if (hash.startsWith("#/map")) return { page: "map" };
  // #/favorites and #/search are pre-handoff routes folded into Spots
  if (hash.startsWith("#/spots") || hash.startsWith("#/favorites") || hash.startsWith("#/search"))
    return { page: "spots" };
  if (hash.startsWith("#/settings") || hash.startsWith("#/account")) return { page: "settings" };
  return { page: "today" };
}

const TABS: { tab: Tab; label: string; icon: typeof HomeIcon }[] = [
  { tab: "today", label: "Today", icon: HomeIcon },
  { tab: "spots", label: "Spots", icon: StarIcon },
  { tab: "map", label: "Map", icon: MapIcon },
  { tab: "settings", label: "Settings", icon: GearIcon },
];

function TabBar({ active }: { active: Tab }) {
  return (
    <nav class="tabs" aria-label="Main">
      {TABS.map(({ tab, label, icon: Icon }) => (
        <a
          key={tab}
          class={active === tab ? "on" : ""}
          href={TAB_ROUTES[tab]}
          aria-current={active === tab ? "page" : undefined}
        >
          <Icon />
          <span>{label}</span>
        </a>
      ))}
    </nav>
  );
}

export function App() {
  const [route, setRoute] = useState<Route>(() => {
    // reopen on the last used tab (only when landing on the bare root)
    if ((location.hash === "" || location.hash === "#/") && lastTab() !== "today") {
      location.replace(TAB_ROUTES[lastTab()]);
      return parseRoute(TAB_ROUTES[lastTab()]);
    }
    return parseRoute(location.hash);
  });
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => applyTheme(theme), [theme]);

  useEffect(() => {
    const onHash = () => {
      const r = parseRoute(location.hash);
      setRoute(r);
      if (r.page !== "spot") saveLastTab(r.page);
      scrollTo(0, 0);
    };
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  const onSetTheme = (next: Theme) => {
    setTheme(next);
    saveTheme(next);
  };

  return (
    <div class="app">
      {route.page === "spot" ? (
        <SpotPage id={route.id} />
      ) : route.page === "map" ? (
        <MapPage theme={theme} />
      ) : route.page === "spots" ? (
        <SpotsPage />
      ) : route.page === "settings" ? (
        <SettingsPage theme={theme} onSetTheme={onSetTheme} />
      ) : (
        <TodayPage />
      )}
      {route.page !== "spot" && <TabBar active={route.page} />}
    </div>
  );
}
