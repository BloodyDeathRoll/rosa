import { useEffect, useState } from "preact/hooks";
import { HomeIcon, MapIcon, StarIcon, UserIcon } from "./components/icons";
import { InstallPrompt } from "./components/InstallPrompt";
import { AboutPage, type AboutDoc } from "./pages/AboutPage";
import { MapPage } from "./pages/MapPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SearchPage } from "./pages/SearchPage";
import { SpotPage } from "./pages/SpotPage";
import { SpotsPage } from "./pages/SpotsPage";
import { TodayPage } from "./pages/TodayPage";
import { applyTheme, initialTheme, saveTheme, type Theme } from "./theme";
import { lastTab, saveLastTab, TAB_ROUTES, type Tab } from "./tabs";

type Route =
  | { page: "today" }
  | { page: "spots" }
  | { page: "search" }
  | { page: "map" }
  | { page: "settings" }
  | { page: "about"; doc: AboutDoc }
  | { page: "spot"; id: string };

function parseRoute(hash: string): Route {
  const spot = /^#\/spot\/([\w-]+)/.exec(hash);
  if (spot?.[1]) return { page: "spot", id: spot[1] };
  if (hash.startsWith("#/map")) return { page: "map" };
  if (hash.startsWith("#/search")) return { page: "search" };
  // #/favorites is a pre-handoff route folded into Spots
  if (hash.startsWith("#/spots") || hash.startsWith("#/favorites")) return { page: "spots" };
  const about = /^#\/about\/(how|reading|terms|privacy)/.exec(hash);
  if (about?.[1]) return { page: "about", doc: about[1] as AboutDoc };
  if (hash.startsWith("#/settings") || hash.startsWith("#/account")) return { page: "settings" };
  return { page: "today" };
}

const TABS: { tab: Tab; label: string; icon: typeof HomeIcon }[] = [
  { tab: "today", label: "Today", icon: HomeIcon },
  { tab: "spots", label: "Spots", icon: StarIcon },
  { tab: "map", label: "Map", icon: MapIcon },
  { tab: "settings", label: "Profile", icon: UserIcon },
];

function TabBar({ active }: { active: Tab | null }) {
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
      if (r.page !== "spot" && r.page !== "about" && r.page !== "search") saveLastTab(r.page);
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
      ) : route.page === "search" ? (
        <SearchPage />
      ) : route.page === "settings" ? (
        <SettingsPage theme={theme} onSetTheme={onSetTheme} />
      ) : route.page === "about" ? (
        <AboutPage doc={route.doc} />
      ) : (
        <TodayPage />
      )}
      {/* Search stays focused (no nav). Spot pages show the nav but light no tab
          (you're deeper than any section). About lives under Profile. */}
      {route.page !== "search" && (
        <TabBar
          active={
            route.page === "spot" ? null : route.page === "about" ? "settings" : route.page
          }
        />
      )}
      <InstallPrompt />
    </div>
  );
}
