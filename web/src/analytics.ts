/** Vercel Web Analytics - visitor and pageview counts, nothing else.
    Rosa had no way to answer "how many users do we have"; the push-subscription
    list only counts devices that opted into notifications.

    Auto-track is off on purpose: every view is sent here, on the router's own
    event, so a pushState and the popstate that the back button fires can never
    be counted twice. */
import { inject, pageview } from "@vercel/analytics";
import { currentPath, onRouteChange, parseRoute, type Route } from "./router";

/** Every spot page collapses to one row so the report reads as screens, not
    as a spot leaderboard. `path` still carries the real path for the few cases
    where the individual spot matters. */
function routeOf(route: Route): string {
  switch (route.page) {
    case "today":
      return "/";
    case "spot":
      return "/spot/[id]";
    case "about":
      return `/about/${route.doc}`;
    default:
      return `/${route.page}`;
  }
}

export function initAnalytics(): void {
  inject({ disableAutoTrack: true });
  const send = () => {
    pageview({ route: routeOf(parseRoute(currentPath())), path: location.pathname });
  };
  send();
  onRouteChange(send);
}
