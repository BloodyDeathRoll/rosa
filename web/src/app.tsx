import { useEffect, useState } from "preact/hooks";
import { HomeIcon, MapIcon, StarIcon, UserIcon } from "./components/icons";
import { AccountPage } from "./pages/AccountPage";
import { FavoritesPage } from "./pages/FavoritesPage";
import { Home } from "./pages/Home";
import { MapPage } from "./pages/MapPage";
import { SearchPage } from "./pages/SearchPage";
import { SpotPage } from "./pages/SpotPage";
import { applyTheme, initialTheme, saveTheme, type Theme } from "./theme";
import { lastTab, saveLastTab, TAB_ROUTES, type Tab } from "./tabs";

type Route =
  | { page: "home" }
  | { page: "map" }
  | { page: "favorites" }
  | { page: "account" }
  | { page: "search" }
  | { page: "spot"; id: string };

function parseRoute(hash: string): Route {
  const spot = /^#\/spot\/([\w-]+)/.exec(hash);
  if (spot?.[1]) return { page: "spot", id: spot[1] };
  if (hash.startsWith("#/map")) return { page: "map" };
  if (hash.startsWith("#/favorites")) return { page: "favorites" };
  if (hash.startsWith("#/account")) return { page: "account" };
  if (hash.startsWith("#/search")) return { page: "search" };
  return { page: "home" };
}

const TABS: { tab: Tab; label: string; icon: typeof HomeIcon }[] = [
  { tab: "home", label: "Home", icon: HomeIcon },
  { tab: "map", label: "Map", icon: MapIcon },
  { tab: "favorites", label: "Favorites", icon: StarIcon },
  { tab: "account", label: "Account", icon: UserIcon },
];

function TabBar({ active }: { active: Tab | null }) {
  return (
    <nav class="tabs" aria-label="Main">
      {TABS.map(({ tab, label, icon: Icon }) => (
        <a key={tab} href={TAB_ROUTES[tab]} aria-current={active === tab ? "page" : undefined}>
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
    if ((location.hash === "" || location.hash === "#/") && lastTab() !== "home") {
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
      if (r.page === "home" || r.page === "map" || r.page === "favorites" || r.page === "account")
        saveLastTab(r.page);
      scrollTo(0, 0);
    };
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    saveTheme(next);
  };

  const activeTab: Tab | null =
    route.page === "spot" || route.page === "search" ? null : route.page;

  return (
    <>
      {route.page === "spot" ? (
        <SpotPage id={route.id} theme={theme} onToggleTheme={toggleTheme} />
      ) : route.page === "search" ? (
        <SearchPage />
      ) : route.page === "map" ? (
        <MapPage theme={theme} />
      ) : route.page === "favorites" ? (
        <FavoritesPage theme={theme} onToggleTheme={toggleTheme} />
      ) : route.page === "account" ? (
        <AccountPage theme={theme} onToggleTheme={toggleTheme} />
      ) : (
        <Home theme={theme} onToggleTheme={toggleTheme} />
      )}
      {route.page !== "search" && <TabBar active={activeTab} />}
    </>
  );
}
