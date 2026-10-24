/** What each screen says in <head>. Spot pages are refined by SpotPage once the
    spot is known; this sets the shell value the moment the route changes. */
import { DEFAULT_DESCRIPTION, DEFAULT_TITLE, setHead, SITE } from "./head";
import { pathFor, type Route } from "./router";

export const ABOUT_TITLES = {
  how: "How it works",
  reading: "Reading the forecast",
  terms: "Terms of Use",
  privacy: "Privacy Policy",
  contact: "Contact Us",
} as const;

export const ABOUT_DESCRIPTIONS = {
  how: "How Rosa turns NOAA and ECMWF wave models, coastal bathymetry and local wind into a surf rating for every spot - and why the formula is public.",
  reading: "What every number on a Rosa surf forecast means: surf height, swell, period, wind, tide, kJ, pressure, water temperature and the 0-100 rating.",
  terms: "Terms of use for Rosa, the free surf forecast.",
  privacy: "How Rosa handles your data: what is stored, where, and how to opt out.",
  contact: "Get in touch with Rosa - report a spot, ask a question, suggest a break.",
} as const;

export function headFor(route: Route): void {
  const path = pathFor(route);
  switch (route.page) {
    case "today":
      setHead({
        title: DEFAULT_TITLE,
        description: DEFAULT_DESCRIPTION,
        path,
        jsonLd: {
          "@type": "WebApplication",
          name: "Rosa",
          url: SITE,
          applicationCategory: "WeatherApplication",
          operatingSystem: "Any",
          offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
          description: DEFAULT_DESCRIPTION,
        },
      });
      return;
    case "spot":
      // SpotPage owns its head (from the index entry, then the payload); setting
      // a placeholder here would blank the prerendered title on every cold load
      return;
    case "about":
      setHead({
        title: `${ABOUT_TITLES[route.doc]} | Rosa`,
        description: ABOUT_DESCRIPTIONS[route.doc],
        path,
      });
      return;
    case "map":
      setHead({
        title: "Surf map - every spot, rated right now | Rosa",
        description: "Live surf map, worldwide. Tap a spot for its 16-day forecast.",
        path,
      });
      return;
    case "charts":
      setHead({
        title: "Swell charts - animated wave height and period | Rosa",
        description: "Animated swell charts for every ocean, 16 days out.",
        path,
      });
      return;
    case "spots":
      setHead({ title: "Your spots | Rosa", path, noindex: true });
      return;
    case "search":
      setHead({ title: "Search spots | Rosa", path, noindex: true });
      return;
    case "settings":
      setHead({ title: "Profile | Rosa", path, noindex: true });
      return;
  }
}
