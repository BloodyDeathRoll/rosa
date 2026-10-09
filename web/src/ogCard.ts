/** The per-spot share card (OPEN-ITEMS 35c): an SVG overlay - the Rosa mark, the spot
    name and "town, region" - that `scripts/og-cards.mjs` rasterises (resvg) over the
    darkened og.jpg photo and writes to `dist/og/spot/{id}.jpg` at build time. Static on
    purpose: crawlers cache an og:image for days, so a rating baked in would go stale.
    Pure string code, no DOM, so the prerender bundle can run it in node. */

export const OG_W = 1200;
export const OG_H = 630;
const PAD = 64;
const TEXT_W = OG_W - 2 * PAD;

/** Bump to regenerate every cached card (scripts/og-cards.mjs keys its cache on it). */
export const OG_CARD_VERSION = "1";

export function escXml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}

/** Rough advance width of `s` in Inter, in em - resvg cannot measure before it renders,
    and a card only needs to know whether a line fits, not the exact pixel. Errs wide. */
export function textEm(s: string, bold: boolean): number {
  let w = 0;
  for (const ch of s) {
    if (ch === " ") w += 0.28;
    else if ("ijlI.,'’:;|!".includes(ch)) w += 0.3;
    else if ("ftr()-".includes(ch)) w += 0.4;
    else if ("mwMW".includes(ch)) w += 0.9;
    else if (/[A-ZÀ-ÖØ-ÞÆŒ]/.test(ch)) w += 0.72;
    else if (/[0-9]/.test(ch)) w += 0.62;
    else w += 0.58;
  }
  return bold ? w * 1.04 : w;
}

/** Greedy word wrap of `text` at `size` px into lines no wider than `max` px. */
function wrap(text: string, size: number, max: number, bold: boolean): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let cur = "";
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w;
    if (!cur || textEm(next, bold) * size <= max) cur = next;
    else {
      lines.push(cur);
      cur = w;
    }
  }
  if (cur) lines.push(cur);
  return lines;
}

/** The biggest name size (96 -> 52 px) at which the name fits in two lines. */
export function fitName(name: string): { size: number; lines: string[] } {
  for (let size = 96; size >= 52; size -= 4) {
    const lines = wrap(name, size, TEXT_W, true);
    if (lines.length <= 2 && lines.every((l) => textEm(l, true) * size <= TEXT_W)) return { size, lines };
  }
  // pathological: hard-cut to two lines at the floor size
  const size = 52;
  const lines = wrap(name, size, TEXT_W, true).slice(0, 2);
  return { size, lines: lines.map((l) => fitLine(l, size, true)) };
}

/** `s` shortened with an ellipsis until it fits `TEXT_W` at `size`. */
export function fitLine(s: string, size: number, bold: boolean): string {
  if (textEm(s, bold) * size <= TEXT_W) return s;
  let t = s;
  while (t.length > 1 && textEm(`${t}…`, bold) * size > TEXT_W) t = t.slice(0, -1);
  return `${t.trimEnd()}…`;
}

export interface CardSpot {
  name: string;
  town?: string;
  region?: string;
}

/** "town, region", skipping a part that repeats the name (same rule as head.ts spotHead). */
export function cardWhere(sp: CardSpot): string {
  return [sp.town, sp.region].filter((s): s is string => !!s && s !== sp.name).join(", ");
}

/** The overlay SVG for one spot. `mark` is the brand mark's path data and viewBox
    (public/favicon.svg), passed in so this stays free of file IO. */
export function ogCardSvg(sp: CardSpot, mark: { d: string; viewBox: string }): string {
  const { size, lines } = fitName(sp.name);
  const whereSize = 38;
  const where = fitLine(cardWhere(sp), whereSize, false);
  const lh = Math.round(size * 1.08);
  const whereY = OG_H - PAD;
  const lastNameY = whereY - whereSize - 26;
  const nameTspans = lines
    .map((l, i) => `<tspan x="${PAD}" y="${lastNameY - (lines.length - 1 - i) * lh}">${escXml(l)}</tspan>`)
    .join("");
  const markH = 60;
  const [, , vw = 1, vh = 1] = mark.viewBox.split(/\s+/).map(Number);
  const markW = Math.round((markH * vw) / vh);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${OG_W}" height="${OG_H}" viewBox="0 0 ${OG_W} ${OG_H}">
  <defs>
    <linearGradient id="shade" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#000" stop-opacity="0.55"/>
      <stop offset="0.35" stop-color="#000" stop-opacity="0.15"/>
      <stop offset="0.55" stop-color="#000" stop-opacity="0.35"/>
      <stop offset="1" stop-color="#000" stop-opacity="0.88"/>
    </linearGradient>
  </defs>
  <rect width="${OG_W}" height="${OG_H}" fill="url(#shade)"/>
  <svg x="${PAD}" y="${PAD - 6}" width="${markW}" height="${markH}" viewBox="${mark.viewBox}"><path fill="#11b7f2" d="${mark.d}"/></svg>
  <text x="${PAD + markW + 18}" y="${PAD + 40}" font-family="Inter" font-size="44" font-weight="700" fill="#ffffff">Rosa</text>
  <text x="${PAD + markW + 18 + 122}" y="${PAD + 40}" font-family="Inter" font-size="30" font-weight="400" fill="#d6dde6">Free surf forecast</text>
  <text font-family="Inter" font-size="${size}" font-weight="700" fill="#ffffff">${nameTspans}</text>
  ${where ? `<text x="${PAD}" y="${whereY}" font-family="Inter" font-size="${whereSize}" font-weight="400" fill="#d6dde6">${escXml(where)}</text>` : ""}
</svg>`;
}
