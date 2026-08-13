// Rasterise the PWA icons from the SVG sources.
//
// Chrome on Android mints its WebAPK from the PNGs, not the SVGs, so whenever the
// brand mark changes colour the PNGs have to be re-rendered or the installed app
// keeps the old one. This is that step: `node tools/render-icons.mjs`.
//
// Headless Chrome is the rasteriser because this box has no rsvg-convert,
// inkscape or ImageMagick, and Chrome is the engine that renders these icons in
// production anyway. Note: no --virtual-time-budget - it stalls on pages that
// animate, and it buys nothing for a static SVG.

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const PUBLIC = join(dirname(fileURLToPath(import.meta.url)), "..", "public");

/** src: SVG to render · out: PNG to write · px: square size · mark: optional
    --brand-mark override (the notification badge is a white silhouette). */
const TARGETS = [
  // the "any" icons are the bare mark on transparency (favicon.svg), not the
  // rounded tile - that one is what "maskable" is for
  { src: "favicon.svg", out: "icon-192.png", px: 192 },
  { src: "favicon.svg", out: "icon-512.png", px: 512 },
  { src: "icon-maskable.svg", out: "icon-maskable-192.png", px: 192 },
  { src: "icon-maskable.svg", out: "icon-maskable-512.png", px: 512 },
  { src: "favicon.svg", out: "notify-badge.png", px: 96, mark: "#ffffff" },
];

const work = mkdtempSync(join(tmpdir(), "rosa-icons-"));

for (const { src, out, px, mark } of TARGETS) {
  // Inline the SVG rather than <img src>: that way the page can override
  // --brand-mark, which never crosses into an SVG loaded as its own document.
  const svg = readFileSync(join(PUBLIC, src), "utf8").replace(/<\?xml[^>]*\?>/, "");
  const page = join(work, `${out}.html`);
  // The override has to come after the SVG: the file declares :root
  // --brand-mark itself, and its inlined <style> would otherwise win on order.
  writeFileSync(
    page,
    `<!doctype html><meta charset="utf-8">
<style>
  html, body { margin: 0; background: transparent; }
  svg { display: block; width: ${px}px; height: ${px}px; }
</style>${svg}
${mark ? `<style>:root { --brand-mark: ${mark}; }</style>` : ""}`,
  );

  execFileSync("google-chrome", [
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    "--default-background-color=00000000", // keep transparency
    `--window-size=${px},${px}`,
    `--screenshot=${join(PUBLIC, out)}`,
    `file://${page}`,
  ]);
  console.log(`${out}  ${px}x${px}  ${src}${mark ? `  (${mark})` : ""}`);
}

rmSync(work, { recursive: true, force: true });
