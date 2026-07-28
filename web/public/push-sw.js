/* Swell-alert push handlers - imported into the generated Workbox service
   worker via workbox.importScripts (vite.config.ts). Plain JS, SW scope. */

self.addEventListener("push", (event) => {
  let d = {};
  try {
    d = event.data ? event.data.json() : {};
  } catch {
    /* non-JSON push - show the fallback title */
  }
  // Android shows the installed app's identity icon on its own, so the brand
  // tile as payload icon duplicates it; an omitted or transparent icon draws
  // an auto-generated letter monogram - the slot never stays empty (tested on
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
      // feedback asks carry 👍/👎 action buttons answerable from the lock screen
      actions: Array.isArray(d.actions) ? d.actions : [],
      data: { url: d.url || "/", feedback: d.feedback || null },
    })
  );
});

// SW is a static file - no build-time env; same origin the app is built with
var FEEDBACK_API = "https://rosa-push.vercel.app/api/feedback";

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const data = event.notification.data || {};
  // Step 1 of the feedback ask - "surfed it?". No ends it silently (a session
  // that never happened has nothing to say about the forecast); Yes raises
  // step 2 in place, carrying the same feedback block.
  if (event.action === "surfed-no") return;
  if (event.action === "surfed-yes" && data.feedback) {
    event.waitUntil(
      self.registration.showNotification("How was the forecast?", {
        body: event.notification.body || "",
        tag: event.notification.tag || "rosa-fb",
        icon: /android/i.test(navigator.userAgent) ? "/notify-badge.png" : "/notify-icon.png",
        badge: "/notify-badge.png",
        actions: [
          { action: "up", title: "👍 Nailed it" },
          { action: "down", title: "👎 Off" },
        ],
        data: data,
      })
    );
    return;
  }
  // 👍/👎 tapped on a feedback ask: POST the verdict right from the worker -
  // the app never needs to open
  if ((event.action === "up" || event.action === "down") && data.feedback) {
    event.waitUntil(
      fetch(FEEDBACK_API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          Object.assign({}, data.feedback, { verdict: event.action })
        ),
      }).catch(() => undefined)
    );
    return;
  }
  const url = data.url || "/";
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
