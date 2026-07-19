import { useEffect, useState } from "preact/hooks";
import { Home } from "./pages/Home";
import { MapPage } from "./pages/MapPage";
import { SpotPage } from "./pages/SpotPage";
import { applyTheme, initialTheme, saveTheme, type Theme } from "./theme";

type Route = { page: "spots" } | { page: "map" } | { page: "spot"; id: string };

function parseRoute(hash: string): Route {
  const spot = /^#\/spot\/([\w-]+)/.exec(hash);
  if (spot?.[1]) return { page: "spot", id: spot[1] };
  if (hash.startsWith("#/map")) return { page: "map" };
  return { page: "spots" };
}

function TabBar({ active }: { active: "spots" | "map" | "none" }) {
  return (
    <nav class="tabs" aria-label="Main">
      <a href="#/" aria-current={active === "spots" ? "page" : undefined}>
        Spots
      </a>
      <a href="#/map" aria-current={active === "map" ? "page" : undefined}>
        Map
      </a>
    </nav>
  );
}

export function App() {
  const [route, setRoute] = useState(() => parseRoute(location.hash));
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => applyTheme(theme), [theme]);

  useEffect(() => {
    const onHash = () => {
      setRoute(parseRoute(location.hash));
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

  return (
    <>
      {route.page === "spot" ? (
        <SpotPage id={route.id} theme={theme} onToggleTheme={toggleTheme} />
      ) : route.page === "map" ? (
        <MapPage />
      ) : (
        <Home theme={theme} onToggleTheme={toggleTheme} />
      )}
      <TabBar active={route.page === "spot" ? "none" : route.page} />
    </>
  );
}
