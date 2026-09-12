// Prerendered shells for crawlers (2026-09-12). Rosa is a static SPA; every
// screen has a real path since the hash router went, and Vercel serves the file
// written here for it (vercel-output.json). Each shell is dist/index.html with
// the <head> rewritten for that screen (title, description, canonical, Open
// Graph, JSON-LD) and crawlable text inside #app, which the app replaces on
// first render. Also writes sitemap.xml.
//
// Spot facts come from the published index (name, region, town, lat, lon),
// fetched from the data CDN so the shells match what the app shows; the local
// copy in public/data is the fallback. The forecast itself is never baked in:
// it changes four times a day and the app renders it live.
//
// Keep the title/description wording in step with src/head.ts (spotHead) and
// src/seo.ts - the app sets the same values when it navigates.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

const SITE = "https://rosa.surf";
const DIST = "dist";
const DEFAULT_DESCRIPTION =
  "Free surf forecast for 1,900+ spots worldwide: wave height, swell, wind, tide and a 0-100 rating, 7 days out, updated four times a day. Should I surf, when, where?";

const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const env = Object.fromEntries(
  readFileSync(".env.production", "utf8")
    .split("\n")
    .map((l) => l.match(/^(VITE_\w+)=(.*)$/))
    .filter(Boolean)
    .map((m) => [m[1], m[2].trim()]),
);

async function loadIndex() {
  const base = env.VITE_DATA_BASE;
  if (base) {
    try {
      const r = await fetch(`${base}/data/index.json`, { signal: AbortSignal.timeout(20000) });
      if (r.ok) return (await r.json()).spots;
      console.warn(`prerender: ${base}/data/index.json -> ${r.status}, using public/data`);
    } catch (e) {
      console.warn(`prerender: index fetch failed (${e.message}), using public/data`);
    }
  }
  return JSON.parse(readFileSync("public/data/index.json", "utf8")).spots;
}

const template = readFileSync(join(DIST, "index.html"), "utf8");
if (!template.includes("<!-- prerender:app-static -->")) throw new Error("prerender: index.html lost its static block");

/** dist/index.html with this screen's head and static body. */
function shell({ title, description = DEFAULT_DESCRIPTION, path, noindex = false, jsonLd = null, body }) {
  const url = SITE + path;
  let html = template;
  const set = (re, repl) => {
    if (!re.test(html)) throw new Error(`prerender: template lacks ${re}`);
    html = html.replace(re, repl);
  };
  set(/<title>[^<]*<\/title>/, `<title>${esc(title)}</title>`);
  set(/<meta\s+name="description"\s+content="[^"]*"\s*\/>/, `<meta name="description" content="${esc(description)}" />`);
  set(/<link rel="canonical" href="[^"]*" \/>/, `<link rel="canonical" href="${esc(url)}" />`);
  set(/<meta property="og:title" content="[^"]*" \/>/, `<meta property="og:title" content="${esc(title)}" />`);
  set(/<meta\s+property="og:description"\s+content="[^"]*"\s*\/>/, `<meta property="og:description" content="${esc(description)}" />`);
  set(/<meta property="og:url" content="[^"]*" \/>/, `<meta property="og:url" content="${esc(url)}" />`);
  set(/<meta name="twitter:title" content="[^"]*" \/>/, `<meta name="twitter:title" content="${esc(title)}" />`);
  set(/<meta\s+name="twitter:description"\s+content="[^"]*"\s*\/>/, `<meta name="twitter:description" content="${esc(description)}" />`);
  // the WebSite graph belongs to the root only; a screen brings its own or none
  set(
    /<script type="application\/ld\+json">[\s\S]*?<\/script>/,
    jsonLd ? `<script type="application/ld+json">${JSON.stringify({ "@context": "https://schema.org", ...jsonLd })}</script>` : "",
  );
  if (noindex) html = html.replace("</title>", `</title>\n    <meta name="robots" content="noindex, follow" />`);
  set(/<!-- prerender:app-static -->[\s\S]*<!-- \/prerender:app-static -->/, body);
  return html;
}

function write(rel, html) {
  const p = join(DIST, rel);
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, html);
}

const km = (a, b) => {
  const r = Math.PI / 180;
  const x = (b.lon - a.lon) * r * Math.cos(((a.lat + b.lat) / 2) * r);
  const y = (b.lat - a.lat) * r;
  return Math.sqrt(x * x + y * y) * 6371;
};

/** src/head.ts spotHead, in build-time form. */
function spotPage(id, sp, nearby) {
  const where = [sp.town, sp.region].filter((s) => s && s !== sp.name).join(", ");
  const title = `${sp.name} surf forecast${where ? ` - ${where}` : ""} | Rosa`;
  const description = `Free 7-day surf forecast for ${sp.name}${where ? ` (${where})` : ""}: wave height, swell, wind, tide, water temperature and a 0-100 surf rating, updated four times a day.`;
  const jsonLd = {
    "@type": "Place",
    name: sp.name,
    url: `${SITE}/spot/${id}`,
    geo: { "@type": "GeoCoordinates", latitude: sp.lat, longitude: sp.lon },
    ...(sp.region
      ? { address: { "@type": "PostalAddress", ...(sp.town ? { addressLocality: sp.town } : {}), addressRegion: sp.region } }
      : {}),
  };
  const body = `<main class="page seo-static">
        <h1>${esc(sp.name)} surf forecast</h1>
        <p>${esc(where ? `${sp.name}, ${where}.` : `${sp.name}.`)} ${sp.lat.toFixed(4)}, ${sp.lon.toFixed(4)}.</p>
        <p>Free 7-day surf forecast for ${esc(sp.name)}: wave height, swell size, period and direction, wind speed and direction, tide, water temperature and a 0-100 surf rating for every hour, updated four times a day from the NOAA GFS-Wave and ECMWF wave models. The rating formula is public - see <a href="/about/how">how it works</a> and <a href="/about/reading">reading the forecast</a>.</p>
        ${
          nearby.length
            ? `<h2>Other surf spots near ${esc(sp.name)}</h2>
        <ul>
          ${nearby.map(([nid, n, d]) => `<li><a href="/spot/${nid}">${esc(n.name)}</a> - ${Math.round(d)} km</li>`).join("\n          ")}
        </ul>`
            : ""
        }
        <p><a href="/">Rosa - free surf forecast</a> · <a href="/map">Surf map</a></p>
      </main>`;
  return shell({ title, description, path: `/spot/${id}`, jsonLd, body });
}

const ABOUT = {
  how: ["How it works", "How Rosa turns NOAA and ECMWF wave models, coastal bathymetry and local wind into a surf rating for every spot - and why the formula is public."],
  reading: ["Reading the forecast", "What every number on a Rosa surf forecast means: surf height, swell, period, wind, tide, kJ, pressure, water temperature and the 0-100 rating."],
  terms: ["Terms of Use", "Terms of use for Rosa, the free surf forecast."],
  privacy: ["Privacy Policy", "How Rosa handles your data: what is stored, where, and how to opt out."],
  contact: ["Contact Us", "Get in touch with Rosa - report a spot, ask a question, suggest a break."],
};

const SCREENS = {
  map: ["Surf map - every spot, rated right now | Rosa", "A live map of 1,900+ surf spots worldwide, each coloured by today's surf rating. Tap a spot for its 7-day forecast.", false],
  charts: ["Swell charts - animated wave height and period | Rosa", "Animated swell height, period and direction charts for every ocean, 7 days out, from the GFS-Wave and ECMWF models.", false],
  spots: ["Your spots | Rosa", DEFAULT_DESCRIPTION, true],
  search: ["Search spots | Rosa", DEFAULT_DESCRIPTION, true],
  settings: ["Profile | Rosa", DEFAULT_DESCRIPTION, true],
};

const spots = await loadIndex();
const ids = Object.keys(spots).sort();
if (ids.length < 100) throw new Error(`prerender: only ${ids.length} spots in the index`);

const { renderAbout } = await import("../dist-ssr/prerender-entry.js");

// spot shells, each linking its 8 nearest neighbours (crawl paths between spots)
const entries = ids.map((id) => [id, spots[id]]);
for (const [id, sp] of entries) {
  const nearby = entries
    .filter(([nid]) => nid !== id)
    .map(([nid, n]) => [nid, n, km(sp, n)])
    .sort((a, b) => a[2] - b[2])
    .slice(0, 8);
  write(`spot/${id}.html`, spotPage(id, sp, nearby));
}

for (const [doc, [title, description]] of Object.entries(ABOUT)) {
  // the contact form reads the browser at render time and has no text worth
  // indexing - it gets the plain shell
  const body =
    doc === "contact"
      ? `<main class="page seo-static"><h1>${esc(title)}</h1><p>${esc(description)}</p><p><a href="/">Rosa - free surf forecast</a></p></main>`
      : renderAbout(doc);
  write(`about/${doc}.html`, shell({ title: `${title} | Rosa`, description, path: `/about/${doc}`, body }));
}

for (const [screen, [title, description, noindex]] of Object.entries(SCREENS)) {
  write(`${screen}.html`, shell({
    title,
    description,
    path: `/${screen}`,
    noindex,
    body: `<main class="page seo-static"><h1>${esc(title.replace(/ \| Rosa$/, ""))}</h1><p>${esc(description)}</p><p><a href="/">Rosa - free surf forecast</a></p></main>`,
  }));
}

// sitemap: the public screens; personal ones (spots, search, settings) are noindex
const urls = ["/", "/map", "/charts", ...Object.keys(ABOUT).map((d) => `/about/${d}`), ...ids.map((id) => `/spot/${id}`)];
write(
  "sitemap.xml",
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls
    .map((u) => `  <url><loc>${esc(SITE + u)}</loc></url>`)
    .join("\n")}\n</urlset>\n`,
);

console.log(`prerender: ${ids.length} spot pages, ${Object.keys(ABOUT).length} about pages, ${Object.keys(SCREENS).length} screens, sitemap ${urls.length} urls`);
