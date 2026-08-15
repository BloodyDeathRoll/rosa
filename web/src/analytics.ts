/** Vercel Web Analytics - visitor and pageview counts, nothing else.
    Rosa had no way to answer "how many users do we have"; the push-subscription
    list only counts devices that opted into notifications.

    Auto-track is off on purpose. The injected script hooks `history.pushState`,
    and Rosa navigates by assigning `location.hash`, which it never sees - so the
    only view it would ever report is the cold start. Every view is sent here
    instead, which also rules out a double count on the back button. */
import { inject, pageview } from "@vercel/analytics";
import { parseRoute, type Route } from "./app";

/** Every spot page collapses to one row so the report reads as screens, not
    as a spot leaderboard. `path` still carries the real hash for the few cases
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
    pageview({ route: routeOf(parseRoute(location.hash)), path: location.hash.slice(1) || "/" });
  };
  send();
  addEventListener("hashchange", send);
}
