import preact from "@preact/preset-vite";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    preact(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "Rosa — surf forecast",
        short_name: "Rosa",
        description: "Should I surf, when, where?",
        theme_color: "#ffffff",
        background_color: "#ffffff",
        display: "standalone",
        icons: [
          // the full-bleed maskable tile IS the installed app icon (raw + OS-masked);
          // the rounded icon.svg stays as a plain-"any" fallback for contexts that want it
          { src: "/icon-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "any maskable" },
          { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" }
        ]
      },
      workbox: {
        // swell-alert push/notificationclick handlers ride along inside the
        // generated SW (public/push-sw.js) — generateSW strategy kept intact
        importScripts: ["push-sw.js"],
        // a new build's SW takes over immediately and deletes prior precaches, so a
        // stale app shell / forecast can't linger on a device across deploys
        skipWaiting: true,
        clientsClaim: true,
        cleanupOutdatedCaches: true,
        // app shell precached; the heavy maplibre chunk is fetched (and then cached)
        // only when the Map tab opens; forecast JSON served stale-while-revalidate so
        // the last forecast is readable offline and refreshes in the background
        // (latin Inter subset precached so the offline app keeps its typeface)
        // splash.jpg precached explicitly: the branded splash paints before the JS
        // bundle, so on an installed-PWA cold start it must come from the SW cache
        // or it never appears (about/*.jpg deliberately excluded — secondary pages)
        globPatterns: ["**/*.{js,css,html,svg}", "**/inter-latin-wght*.woff2", "splash.jpg"],
        globIgnores: ["**/maplibre-gl-*"],
        runtimeCaching: [
          {
            urlPattern: ({ url }) => /\/assets\/maplibre-gl-/.test(url.pathname),
            handler: "CacheFirst",
            options: {
              cacheName: "rosa-map-lib",
              expiration: { maxEntries: 4, maxAgeSeconds: 60 * 60 * 24 * 30 }
            }
          },
          {
            // forecasts must be fresh when online — cache is the offline fallback,
            // never a first answer (stale coords/forecasts looked like data bugs)
            urlPattern: ({ url }) => url.pathname.startsWith("/data/"),
            handler: "NetworkFirst",
            options: {
              // bump the version to orphan any previously-cached forecast payloads
              cacheName: "rosa-data-v2",
              networkTimeoutSeconds: 4,
              expiration: { maxEntries: 64, maxAgeSeconds: 60 * 60 * 24 * 7 }
            }
          }
        ]
      }
    })
  ]
});
