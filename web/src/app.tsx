import { useEffect, useState } from "preact/hooks";
import { HomeIcon, MapIcon, StarIcon, UserIcon, WavesIcon } from "./components/icons";
import { BottomGlow } from "./components/BottomGlow";
import { DesktopBar } from "./components/DesktopBar";
import { InstallPrompt } from "./components/InstallPrompt";
import { SignInScreen } from "./components/SignInScreen";
import { AboutPage, type AboutDoc } from "./pages/AboutPage";
import { ChartsPage } from "./pages/ChartsPage";
import { MapPage } from "./pages/MapPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SearchPage } from "./pages/SearchPage";
import { SpotPage } from "./pages/SpotPage";
import { SpotsPage } from "./pages/SpotsPage";
import { scrollToTop } from "./scroller";
import { TodayPage } from "./pages/TodayPage";
import { applyTheme, initialTheme, saveTheme, type Theme } from "./theme";
import { TAB_ROUTES, type Tab } from "./tabs";

export type Route =
  | { page: "today" }
  | { page: "spots" }
  | { page: "search" }
  | { page: "map" }
  | { page: "charts" }
  | { page: "settings" }
  | { page: "about"; doc: AboutDoc }
  | { page: "spot"; id: string };

export function parseRoute(hash: string): Route {
  const spot = /^#\/spot\/([\w-]+)/.exec(hash);
  if (spot?.[1]) return { page: "spot", id: spot[1] };
  if (hash.startsWith("#/map")) return { page: "map" };
  if (hash.startsWith("#/charts")) return { page: "charts" };
  if (hash.startsWith("#/search")) return { page: "search" };
  // #/favorites is a pre-handoff route folded into Spots
  if (hash.startsWith("#/spots") || hash.startsWith("#/favorites")) return { page: "spots" };
  const about = /^#\/about\/(how|reading|terms|privacy|contact)/.exec(hash);
  if (about?.[1]) return { page: "about", doc: about[1] as AboutDoc };
  if (hash.startsWith("#/settings") || hash.startsWith("#/account")) return { page: "settings" };
  return { page: "today" };
}

const TABS: { tab: Tab; label: string; icon: typeof HomeIcon }[] = [
  { tab: "today", label: "Today", icon: HomeIcon },
  { tab: "spots", label: "Spots", icon: StarIcon },
  { tab: "map", label: "Map", icon: MapIcon },
  { tab: "charts", label: "Charts", icon: WavesIcon },
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
  // A launch always lands on Today. Reopening on the last used tab meant a cold
  // start could drop you straight onto the Map, which answers none of "should I
  // surf, when, where?" until you've panned it. A deep link still wins - only a
  // bare root resolves to Today.
  const [route, setRoute] = useState<Route>(() => parseRoute(location.hash));
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => applyTheme(theme), [theme]);

  useEffect(() => {
    const onHash = () => {
      const r = parseRoute(location.hash);
      setRoute(r);
      scrollToTop();
    };
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  const onSetTheme = (next: Theme) => {
    setTheme(next);
    saveTheme(next);
  };

  // the section a route belongs to: none on a spot page, Profile for About
  const active: Tab | null =
    route.page === "spot" || route.page === "search"
      ? null
      : route.page === "about"
        ? "settings"
        : route.page;

  return (
    <div class="app">
      <BottomGlow theme={theme} />
      {/* wide screens only (CSS) - the phone keeps the pill below */}
      <DesktopBar active={active} />
      {route.page === "spot" ? (
        <SpotPage id={route.id} />
      ) : route.page === "map" ? (
        <MapPage theme={theme} />
      ) : route.page === "charts" ? (
        <ChartsPage theme={theme} />
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
      {route.page !== "search" && <TabBar active={active} />}
      <InstallPrompt />
      <SignInScreen />
    </div>
  );
}
