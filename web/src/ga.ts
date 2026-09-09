/** Google Analytics 4 - the layer Vercel Web Analytics cannot reach: where people
    are, what they open, and what they have set.

    INERT WITHOUT AN ID. `VITE_GA_ID` unset means nothing loads, no cookie is set,
    no request leaves the browser, and every export here is a no-op - so this ships
    dark and turns on with one environment variable. Vercel Web Analytics stays
    alongside it on purpose: it is cookieless, so it keeps counting the people who
    decline consent, which is the population GA4 is blindest to.

    Consent Mode v2 with everything DENIED by default. Until someone accepts, gtag
    sends cookieless pings - country, screen and events still arrive, no identifier
    does - and on accept the storage grants are raised. That ordering is the whole
    point of Consent Mode: the tag must be told the defaults BEFORE it loads, which
    is why `bootConsent()` runs before the script tag is written.

    Not sent, ever: name, email, Google `sub`, or anything else that identifies a
    person. That is Google's own rule for GA4 properties, and breaking it gets the
    property terminated - "which spots do surfers in Sri Lanka open" is a question
    about a cohort, and it is answerable without knowing who they are. */
import { parseRoute, type Route } from "./app";
import { consentGranted } from "./consent";

const GA_ID = import.meta.env.VITE_GA_ID as string | undefined;

type GtagArgs = [string, ...unknown[]];
declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: GtagArgs) => void;
  }
}

export const gaEnabled = (): boolean => !!GA_ID;

function gtag(...args: GtagArgs): void {
  if (!GA_ID) return;
  (window.dataLayer ??= []).push(args);
}

/** Same collapse as the Vercel path: every spot is one row, so the report reads as
    screens rather than as a spot leaderboard. The spot id rides on the `spot_view`
    event instead, where it is the point rather than noise. */
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

/** Consent defaults, pushed before gtag.js loads. */
function bootConsent(): void {
  const granted = consentGranted();
  gtag("consent", "default", {
    ad_storage: "denied",
    ad_user_data: "denied",
    ad_personalization: "denied",
    analytics_storage: granted ? "granted" : "denied",
    functionality_storage: "granted",
    security_storage: "granted",
    wait_for_update: 500,
  });
}

/** Raise the analytics grant after someone accepts. Nothing else is ever granted:
    Rosa runs no ads and has nothing to personalise. */
export function gaGrantConsent(): void {
  gtag("consent", "update", { analytics_storage: "granted" });
}

export function gaDenyConsent(): void {
  gtag("consent", "update", { analytics_storage: "denied" });
}

export function initGa(): void {
  if (!GA_ID) return;
  bootConsent();
  gtag("js", new Date());
  // Manual pageviews for the same reason the Vercel path uses them: Rosa navigates
  // by assigning `location.hash`, which gtag's auto pageview never sees, so the only
  // view it would report is the cold start.
  gtag("config", GA_ID, { send_page_view: false, anonymize_ip: true });

  const s = document.createElement("script");
  s.async = true;
  s.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(GA_ID)}`;
  document.head.appendChild(s);

  const send = () => gaPageview();
  send();
  addEventListener("hashchange", send);
}

export function gaPageview(): void {
  if (!GA_ID) return;
  const route = parseRoute(location.hash);
  gtag("event", "page_view", {
    page_title: routeOf(route),
    page_location: location.href,
    page_path: location.hash.slice(1) || "/",
  });
}

/** One event. Keep the parameter names short and stable - GA4 keys them literally,
    and a renamed parameter is a new column with no history behind it. */
export function gaEvent(name: string, params: Record<string, string | number | boolean> = {}): void {
  if (!GA_ID) return;
  gtag("event", name, params);
}

/** What a visitor has SET, as GA4 user properties - the half that turns a hit into
    "surfers in Sri Lanka mostly open Santa Teresa, in metric, on a phone". These are
    preferences, never identity. GA4 caps a property at 24 characters of name and 36
    of value, so keep them short. */
export interface GaPrefs {
  units?: string;
  theme?: string;
  region?: string;
  signed_in?: boolean;
  favorites?: number;
  installed?: boolean;
  push_on?: boolean;
}

export function gaSetPrefs(prefs: GaPrefs): void {
  if (!GA_ID) return;
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(prefs)) {
    if (v === undefined) continue;
    out[k] = String(v).slice(0, 36);
  }
  if (Object.keys(out).length) gtag("set", "user_properties", out);
}
