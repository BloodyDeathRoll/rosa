import { useEffect, useState } from "preact/hooks";
import { HomeIcon, MapIcon, StarIcon, UserIcon, WavesIcon } from "./components/icons";
import { BottomGlow } from "./components/BottomGlow";
import { DesktopBar } from "./components/DesktopBar";
import { DuplicateNote } from "./components/DuplicateNote";
import { InstallPrompt } from "./components/InstallPrompt";
import { ConsentBar } from "./components/ConsentBar";
import { ReportNudge } from "./components/ReportNudge";
import { SignInScreen } from "./components/SignInScreen";
import { AboutPage } from "./pages/AboutPage";
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
import { currentPath, interceptLinks, onRouteChange, parseRoute, type Route } from "./router";
import { headFor } from "./seo";

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
  const [route, setRoute] = useState<Route>(() => parseRoute(currentPath()));
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => applyTheme(theme), [theme]);

  useEffect(() => {
    interceptLinks();
    return onRouteChange(() => {
      setRoute(parseRoute(currentPath()));
      scrollToTop();
    });
  }, []);

  // title, description, canonical, JSON-LD per screen (SpotPage refines its own
  // once it knows the spot)
  useEffect(() => headFor(route), [route]);

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
      <ConsentBar />
      <ReportNudge />
      <InstallPrompt />
      <DuplicateNote />
      <SignInScreen />
    </div>
  );
}
