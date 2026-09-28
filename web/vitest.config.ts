import preact from "@preact/preset-vite";
import { defineConfig } from "vitest/config";

/** Unit + render tests (every src test file). Deliberately not vite.config.ts: the PWA
    plugin there generates a service worker, which a test run has no use for. */
export default defineConfig({
  plugins: [preact()],
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
