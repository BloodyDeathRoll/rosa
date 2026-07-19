import { useEffect, useState } from "preact/hooks";
import { Home } from "./pages/Home";
import { SpotPage } from "./pages/SpotPage";

function parseRoute(hash: string): { page: "home" } | { page: "spot"; id: string } {
  const m = /^#\/spot\/([\w-]+)/.exec(hash);
  return m?.[1] ? { page: "spot", id: m[1] } : { page: "home" };
}

export function App() {
  const [route, setRoute] = useState(() => parseRoute(location.hash));

  useEffect(() => {
    const onHash = () => {
      setRoute(parseRoute(location.hash));
      scrollTo(0, 0);
    };
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  return route.page === "spot" ? <SpotPage id={route.id} /> : <Home />;
}
