import preact from "@preact/preset-vite";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    preact(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "Rosa - surf forecast",
        short_name: "Rosa",
        description: "Should I surf, when, where?",
        // Android's WebAPK splash (icon on background_color, shown until first
        // paint) can't be skipped - paint it the icon tile's blue so icon and
        // background merge into one solid brand-blue screen. theme_color kept
        // in step or the splash gets a white status bar stripe; the in-app
        // status bar still follows the meta theme-color tags in index.html.
        theme_color: "#032afa",
        background_color: "#032afa",
        display: "standalone",
        // The Play app (android/, a TWA on this origin). Declared so Chrome answers
        // getInstalledRelatedApps() (install.ts). `prefer_related_applications`
        // stays OFF until the Play listing is public: it silences Chrome's PWA
        // install prompt in favour of a store page that today is a 404.
        related_applications: [
          {
            platform: "play",
            id: "surf.rosa.app",
            url: "https://play.google.com/store/apps/details?id=surf.rosa.app"
          }
        ],
        icons: [
          // PNGs first and non-negotiable: Chrome on Android mints a WebAPK from
          // these, and an SVG-only icon set (which desktop Chrome accepts fine)
          // leaves Android with nothing installable - no prompt, no menu entry
          { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          // the maskable tile (#032afa tile, white mark) is the installed app icon
          // AND the WebAPK pre-splash icon - Android prefers maskable for both;
          // it draws on the white background_color
          {
            src: "/icon-maskable-192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "maskable"
          },
          {
            src: "/icon-maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable"
          },
          { src: "/icon-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
          { src: "/favicon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" }
        ]
      },
      workbox: {
        // swell-alert push/notificationclick handlers ride along inside the
        // generated SW (public/push-sw.js) - generateSW strategy kept intact
        importScripts: ["push-sw.js"],
        // a new build's SW takes over immediately and deletes prior precaches, so a
        // stale app shell / forecast can't linger on a device across deploys
        skipWaiting: true,
        clientsClaim: true,
        cleanupOutdatedCaches: true,
        // path routes (/spot/x, /about/how) are served by the precached app shell
        // when the worker owns the navigation (the default navigateFallback);
        // crawler files and data are never answered with the shell
        // /widget/ is the embeddable card: a third-party page frames it, and the
        // installed app's worker would otherwise answer that frame with the shell
        navigateFallbackDenylist: [/^\/data\//, /^\/widget\//, /\.(xml|txt|json)$/],
        // app shell precached; the heavy maplibre chunk is fetched (and then cached)
        // only when the Map tab opens; forecast JSON served stale-while-revalidate so
        // the last forecast is readable offline and refreshes in the background
        // (latin Inter subset precached so the offline app keeps its typeface)
        // splash.jpg precached explicitly: the branded splash paints before the JS
        // bundle, so on an installed-PWA cold start it must come from the SW cache
        // or it never appears (about/*.jpg deliberately excluded - secondary pages)
        globPatterns: ["**/*.{js,css,html,svg}", "**/inter-latin-wght*.woff2", "splash.jpg"],
        globIgnores: ["**/maplibre-gl-*", "widget/**"],
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
            // forecasts must be fresh when online - cache is the offline fallback,
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
