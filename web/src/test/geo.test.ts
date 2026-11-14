import { beforeEach, expect, test, vi } from "vitest";

const fix = { coords: { latitude: 32.1, longitude: 34.8 } };

// the suite runs in node: stand in for the two browser globals geo.ts touches
const store = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
  removeItem: (k: string) => void store.delete(k),
});

beforeEach(() => {
  store.clear();
  vi.resetModules();
});

function stubGeo(impl: (ok: (p: typeof fix) => void, err: (e: unknown) => void) => void) {
  vi.stubGlobal("navigator", { geolocation: { getCurrentPosition: impl } });
}

test("a fix is saved and answers the next load without waiting", async () => {
  stubGeo((ok) => ok(fix));
  expect(await (await import("../geo")).getPosition()).toEqual({ lat: 32.1, lon: 34.8 });

  vi.resetModules();
  stubGeo(() => undefined); // the prompt is never answered
  expect(await (await import("../geo")).getPosition()).toEqual({ lat: 32.1, lon: 34.8 });
});

test("a denied permission forgets the saved fix", async () => {
  localStorage.setItem("rosa.pos", JSON.stringify({ lat: 1, lon: 2 }));
  stubGeo((_ok, err) => err({ code: 1, PERMISSION_DENIED: 1 }));
  await (await import("../geo")).getPosition();
  expect(localStorage.getItem("rosa.pos")).toBeNull();
});
