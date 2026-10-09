/** Per-screen <head>: title, description, canonical, Open Graph and JSON-LD.
    The prerendered shell (`scripts/prerender.mjs`) ships the same values in the
    static HTML for crawlers; this keeps them right as the app navigates. */

export const SITE = "https://rosa.surf";
export const DEFAULT_TITLE = "Rosa - free surf forecast, worldwide";
export const DEFAULT_DESCRIPTION =
  "Free 15-day surf forecast, worldwide. Waves, wind and tide, updated four times a day.";

export interface Head {
  title: string;
  description?: string;
  /** canonical path, e.g. `/spot/pipeline` */
  path: string;
  /** keep this screen out of the index (personal or empty-until-JS screens) */
  noindex?: boolean;
  /** schema.org object for this screen, or null to clear the page one */
  jsonLd?: Record<string, unknown> | null;
  /** share image (1200x630 JPEG) and its alt; default the site-wide og.jpg */
  image?: { url: string; alt: string };
}

export const DEFAULT_IMAGE = { url: `${SITE}/og.jpg`, alt: "Rosa - free surf forecast" };

function meta(sel: string, attr: "name" | "property", key: string): HTMLMetaElement {
  let el = document.head.querySelector<HTMLMetaElement>(sel);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  return el;
}

function link(rel: string): HTMLLinkElement {
  let el = document.head.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`);
  if (!el) {
    el = document.createElement("link");
    el.rel = rel;
    document.head.appendChild(el);
  }
  return el;
}

export function setHead(h: Head): void {
  const description = h.description ?? DEFAULT_DESCRIPTION;
  const url = SITE + h.path;
  document.title = h.title;
  meta('meta[name="description"]', "name", "description").content = description;
  meta('meta[property="og:title"]', "property", "og:title").content = h.title;
  meta('meta[property="og:description"]', "property", "og:description").content = description;
  meta('meta[property="og:url"]', "property", "og:url").content = url;
  meta('meta[name="twitter:title"]', "name", "twitter:title").content = h.title;
  meta('meta[name="twitter:description"]', "name", "twitter:description").content = description;
  const image = h.image ?? DEFAULT_IMAGE;
  meta('meta[property="og:image"]', "property", "og:image").content = image.url;
  meta('meta[property="og:image:alt"]', "property", "og:image:alt").content = image.alt;
  meta('meta[name="twitter:image"]', "name", "twitter:image").content = image.url;
  link("canonical").href = url;
  const robots = meta('meta[name="robots"]', "name", "robots");
  if (h.noindex) robots.content = "noindex, follow";
  else robots.remove();

  const id = "ld-page";
  let ld = document.getElementById(id);
  if (h.jsonLd) {
    if (!ld) {
      ld = document.createElement("script");
      ld.id = id;
      ld.setAttribute("type", "application/ld+json");
      document.head.appendChild(ld);
    }
    ld.textContent = JSON.stringify({ "@context": "https://schema.org", ...h.jsonLd });
  } else {
    ld?.remove();
  }
}

/** Title + description of a spot page. `scripts/prerender.mjs` (`spotPage`)
    writes the same wording into the static shells - keep them in step. */
export function spotHead(spot: { id: string; name: string; region?: string; town?: string; lat: number; lon: number }): Head {
  const where = [spot.town, spot.region].filter((s): s is string => !!s && s !== spot.name).join(", ");
  return {
    title: `${spot.name} surf forecast${where ? ` - ${where}` : ""} | Rosa`,
    description: `Free 15-day surf forecast for ${spot.name}: waves, wind and tide, updated four times a day.`,
    path: `/spot/${spot.id}`,
    // the build's per-spot share card (scripts/og-cards.mjs) - same URL as the shell's
    image: { url: `${SITE}/og/spot/${spot.id}.jpg`, alt: `${spot.name} surf forecast on Rosa` },
    jsonLd: {
      "@type": "Place",
      name: spot.name,
      url: `${SITE}/spot/${spot.id}`,
      geo: { "@type": "GeoCoordinates", latitude: spot.lat, longitude: spot.lon },
      ...(spot.region
        ? {
            address: {
              "@type": "PostalAddress",
              ...(spot.town ? { addressLocality: spot.town } : {}),
              addressRegion: spot.region,
            },
          }
        : {}),
    },
  };
}
