// Render satellite crosshair screenshots for a list of spots.
//
//   node shoot.mjs <spots.json> <out-dir> [zoom]
//
// spots.json: [{ id, name, lat, lon }, ...]  (e.g. produced from data/spots/*.yaml)
// Emits <out-dir>/<id>.png - one satellite tile per spot with a crosshair at its
// coordinate. Deterministic + network-only: no model quota. This is the pre-step
// the Dream rosa-spot-mapper assignment runs before the (sandboxed) vision step.
//
// Requires: a static server for satverify.html and a headless Chrome with
// --remote-debugging-port=9222 already running. See run-local.sh for the wrapper.

import { writeFileSync, readFileSync, mkdirSync } from "node:fs";

const [spotsPath, outDir, zoomArg] = process.argv.slice(2);
const zoom = Number(zoomArg || 16);
const HTTP_PORT = process.env.SPOT_HTTP_PORT || "4174";
const CDP_PORT = process.env.SPOT_CDP_PORT || "9222";
const spots = JSON.parse(readFileSync(spotsPath, "utf8"));
mkdirSync(outDir, { recursive: true });

async function cdp() {
  const t = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/new`, { method: "PUT" })).json();
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let seq = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  const send = (method, params = {}) =>
    new Promise((res) => { const id = ++seq; pending.set(id, res); ws.send(JSON.stringify({ id, method, params })); });
  return { send, close: () => fetch(`http://127.0.0.1:${CDP_PORT}/json/close/${t.id}`) };
}

const { send, close } = await cdp();
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 640, height: 640, deviceScaleFactor: 1, mobile: false });

for (const s of spots) {
  const url = `http://localhost:${HTTP_PORT}/satverify.html?lat=${s.lat}&lon=${s.lon}&z=${zoom}&name=${encodeURIComponent(s.name)}`;
  await send("Page.navigate", { url });
  await new Promise((r) => setTimeout(r, 6000)); // tiles + settle
  const shot = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(`${outDir}/${s.id}.png`, Buffer.from(shot.result.data, "base64"));
  console.log("shot", s.id);
}
await close();
process.exit(0);
