/* Swell-alert push handlers — imported into the generated Workbox service
   worker via workbox.importScripts (vite.config.ts). Plain JS, SW scope. */

self.addEventListener("push", (event) => {
  let d = {};
  try {
    d = event.data ? event.data.json() : {};
  } catch {
    /* non-JSON push — show the fallback title */
  }
  // Android shows the installed app's identity icon on its own, so the brand
  // tile as payload icon duplicates it; an omitted or transparent icon draws
  // an auto-generated letter monogram — the slot never stays empty (tested on
  // One UI, 2026-07-23). Quietest option that renders: the wave-lines glyph,
  // matching the status-bar badge. Desktop has no identity icon, so there the
  // brand tile is the only icon shown.
  const android = /android/i.test(navigator.userAgent);
  event.waitUntil(
    self.registration.showNotification(d.title || "Rosa", {
      body: d.body || "",
      // one tag per swell: a re-send for the same event replaces, never stacks
      tag: d.tag || "rosa-swell",
      icon: android ? "/notify-badge.png" : "/notify-icon.png",
      badge: "/notify-badge.png", // monochrome status-bar glyph
      data: { url: d.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if ("focus" in w) {
          w.navigate(url);
          return w.focus();
        }
      }
      return self.clients.openWindow(url);
    })
  );
});
