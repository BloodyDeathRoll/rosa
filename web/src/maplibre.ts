import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

/** maplibre-gl 6 looks for its worker beside its own module at runtime, a file the
    bundler never copies (the map 404s it and never draws). Hand it the worker Vite
    bundled instead. Loaded on demand so the home page stays light. */
export async function loadMaplibre(): Promise<typeof import("maplibre-gl")> {
  const maplibregl = await import("maplibre-gl");
  maplibregl.setWorkerUrl(workerUrl);
  return maplibregl;
}
