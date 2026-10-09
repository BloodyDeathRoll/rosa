// Per-spot share cards (OPEN-ITEMS 35c, 2026-10-09): one 1200x630 JPEG per spot at
// dist/og/spot/{id}.jpg, the og:image / twitter:image of that spot's prerendered shell.
// The overlay (mark, name, "town, region") is src/ogCard.ts's SVG, rasterised by resvg
// with the committed Inter TTFs (scripts/og-fonts, OFL - resvg cannot read woff2), then
// composited over the darkened og.jpg photo and JPEG-encoded by sharp. Static on purpose:
// crawlers cache an og:image for days, so a rating baked in would be stale and wrong.
//
// Cards are cached outside dist (web/.og-cache, gitignored) keyed by the template version
// and the text they carry, so a rebuild - the VM redeploys on every spot-list change
// (deploy/oracle/publish.sh 3b) - renders only new or renamed spots.
//
// Must run after `vite build` (and after the SSR bundle exists): dist is wiped by a
// fresh build, and these files must never enter the service worker's precache.
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Resvg } from "@resvg/resvg-js";
import sharp from "sharp";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "..");
const FONTS = [join(HERE, "og-fonts/Inter-Bold.ttf"), join(HERE, "og-fonts/Inter-Regular.ttf")];
const CACHE = join(WEB, ".og-cache");
const QUALITY = 70;

const { OG_CARD_VERSION, OG_H, OG_W, cardWhere, ogCardSvg } = await import(join(WEB, "dist-ssr/prerender-entry.js"));

const fav = readFileSync(join(WEB, "public/favicon.svg"), "utf8");
const mark = { d: fav.match(/<path[^>]*\sd="([^"]+)"/)[1], viewBox: fav.match(/viewBox="([^"]+)"/)[1] };

/** og.jpg dimmed and softened once - the shared background of every card. */
const base = await sharp(join(WEB, "public/og.jpg"))
  .resize(OG_W, OG_H)
  .blur(2.5)
  .modulate({ brightness: 0.62 })
  .raw()
  .toBuffer({ resolveWithObject: true });

const key = (sp) =>
  createHash("sha1").update(JSON.stringify([OG_CARD_VERSION, QUALITY, sp.name, cardWhere(sp)])).digest("hex").slice(0, 16);

async function render(sp) {
  const svg = ogCardSvg(sp, mark);
  const png = new Resvg(svg, {
    fitTo: { mode: "width", value: OG_W },
    font: { fontFiles: FONTS, loadSystemFonts: false, defaultFontFamily: "Inter" },
  })
    .render()
    .asPng();
  return sharp(base.data, { raw: base.info })
    .composite([{ input: png }])
    .jpeg({ quality: QUALITY, mozjpeg: true })
    .toBuffer();
}

/** Write a card for every [id, spot] into dist/og/spot; returns counts and timing. */
export async function writeCards(entries, dist) {
  mkdirSync(CACHE, { recursive: true });
  const out = join(dist, "og/spot");
  mkdirSync(out, { recursive: true });
  let rendered = 0;
  let bytes = 0;
  const t0 = Date.now();
  for (const [id, sp] of entries) {
    const cached = join(CACHE, `${key(sp)}.jpg`);
    if (!existsSync(cached)) {
      writeFileSync(cached, await render(sp));
      rendered += 1;
    }
    copyFileSync(cached, join(out, `${id}.jpg`));
    bytes += readFileSync(cached).length;
  }
  return { cards: entries.length, rendered, bytes, ms: Date.now() - t0 };
}
