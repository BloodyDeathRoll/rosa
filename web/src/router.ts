/** Path routing (since 2026-09-12). Rosa navigated by `location.hash` before
    (`#/spot/x`), which a crawler cannot see: every spot page was the one URL
    `/`, so search engines indexed a single page for 1,900 spots. Every screen
    now has a real path (`/spot/x`, `/about/how`), served by Vercel as a
    prerendered shell (`scripts/prerender.mjs`) that the app takes over.

    Old links keep working: `adoptLegacyHash()` rewrites `/#/spot/x?ev=..` to
    `/spot/x?ev=..` at boot (push notifications, share links and the moved-origin
    hand-over still carry the hash form). */

import type { AboutDoc } from "./pages/AboutPage";

export type Route =
  | { page: "today" }
  | { page: "spots" }
  | { page: "search" }
  | { page: "map" }
  | { page: "charts" }
  | { page: "settings" }
  | { page: "about"; doc: AboutDoc }
  | { page: "spot"; id: string };

/** `/spot/x?ev=..`, `#/spot/x`, `spot/x` all parse the same. */
export function parseRoute(path: string): Route {
  const p = path.replace(/^#?\/?/, "/");
  const spot = /^\/spot\/([\w-]+)/.exec(p);
  if (spot?.[1]) return { page: "spot", id: spot[1] };
  if (p.startsWith("/map")) return { page: "map" };
  if (p.startsWith("/charts")) return { page: "charts" };
  if (p.startsWith("/search")) return { page: "search" };
  // /favorites is a pre-handoff route folded into Spots
  if (p.startsWith("/spots") || p.startsWith("/favorites")) return { page: "spots" };
  const about = /^\/about\/(how|reading|terms|privacy|contact)/.exec(p);
  if (about?.[1]) return { page: "about", doc: about[1] as AboutDoc };
  if (p.startsWith("/settings") || p.startsWith("/account")) return { page: "settings" };
  return { page: "today" };
}

/** The canonical path of a route - one URL per screen. */
export function pathFor(route: Route): string {
  switch (route.page) {
    case "today":
      return "/";
    case "spot":
      return `/spot/${route.id}`;
    case "about":
      return `/about/${route.doc}`;
    default:
      return `/${route.page}`;
  }
}

/** Current path + query (never the hash). */
export function currentPath(): string {
  return location.pathname + location.search;
}

const EVENT = "rosa:navigate";

/** In-app navigation: pushState, then tell the app (popstate does not fire for
    pushState). `replace` swaps the current entry instead of adding one. */
export function navigate(path: string, opts: { replace?: boolean } = {}): void {
  if (opts.replace) history.replaceState(null, "", path);
  else history.pushState(null, "", path);
  dispatchEvent(new Event(EVENT));
}

/** Subscribe to every route change: in-app pushes and the back button. */
export function onRouteChange(fn: () => void): () => void {
  addEventListener(EVENT, fn);
  addEventListener("popstate", fn);
  return () => {
    removeEventListener(EVENT, fn);
    removeEventListener("popstate", fn);
  };
}

/** A legacy `#/...` link: move it to the path form, once, before anything
    renders. Its query (`?ev=`, `?import=`) rides along. */
export function adoptLegacyHash(): void {
  const h = location.hash;
  if (!h.startsWith("#/")) return;
  const q = h.indexOf("?");
  const query = q >= 0 ? h.slice(q) : "";
  const target = pathFor(parseRoute(q >= 0 ? h.slice(0, q) : h)) + query;
  history.replaceState(null, "", target);
}

/** Plain `<a href="/...">` links stay plain HTML (crawlers follow them) and are
    turned into in-app navigations here. Modified clicks, downloads, external
    hosts and non-route paths (`/data/`) fall through to the browser. */
export function interceptLinks(): void {
  document.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = (e.target as Element | null)?.closest("a");
    if (!a || a.target || a.hasAttribute("download")) return;
    const href = a.getAttribute("href");
    if (!href || !href.startsWith("/") || href.startsWith("//")) return;
    if (href.startsWith("/data/") || href.startsWith("/about/") && /\.\w+$/.test(href)) return;
    e.preventDefault();
    if (href === currentPath()) return;
    navigate(href);
  });
}
