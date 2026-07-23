/** Web Push client: subscribe this device to swell alerts for the user's
    favorite spots. The subscription is stored by a tiny API (VITE_PUSH_API);
    the pipeline VM sends grouped pushes after each publish cycle. */

import { getFavorites } from "./favorites";

const API = (import.meta.env.VITE_PUSH_API as string | undefined) ?? "";
const VAPID_PUBLIC = (import.meta.env.VITE_VAPID_PUBLIC as string | undefined) ?? "";
const INTENT_KEY = "rosa.push"; // "on" | "off" — the user's choice, survives permission churn

export type PushState = "on" | "off" | "denied" | "unsupported";

export function pushSupported(): boolean {
  return (
    API !== "" &&
    VAPID_PUBLIC !== "" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

function urlB64ToUint8Array(b64: string): Uint8Array {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

async function subscription(): Promise<PushSubscription | null> {
  const reg = await navigator.serviceWorker.ready;
  return reg.pushManager.getSubscription();
}

export async function pushState(): Promise<PushState> {
  if (!pushSupported()) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  if (localStorage.getItem(INTENT_KEY) !== "on") return "off";
  return (await subscription()) ? "on" : "off";
}

async function post(sub: PushSubscription, spots: string[]): Promise<void> {
  const json = sub.toJSON();
  const res = await fetch(`${API}/api/sub`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys, spots }),
  });
  if (!res.ok) throw new Error(`push api ${res.status}`);
}

/** Ask permission, subscribe, and register the device. */
export async function enablePush(): Promise<PushState> {
  if (!pushSupported()) return "unsupported";
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return perm === "denied" ? "denied" : "off";
  const reg = await navigator.serviceWorker.ready;
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlB64ToUint8Array(VAPID_PUBLIC) as BufferSource,
    }));
  await post(sub, getFavorites());
  localStorage.setItem(INTENT_KEY, "on");
  return "on";
}

/** The Profile toggle's opt-out: forget the device server-side and locally. */
export async function disablePush(): Promise<void> {
  localStorage.setItem(INTENT_KEY, "off");
  const sub = await subscription().catch(() => null);
  if (!sub) return;
  await fetch(`${API}/api/sub`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: sub.endpoint }),
  }).catch(() => undefined); // best effort — the sender also prunes dead subs
  await sub.unsubscribe().catch(() => undefined);
}

/** Keep the server's spot list in step with favorites (fire-and-forget). */
export async function syncPushSpots(): Promise<void> {
  if (!pushSupported() || localStorage.getItem(INTENT_KEY) !== "on") return;
  const sub = await subscription().catch(() => null);
  if (sub) await post(sub, getFavorites()).catch(() => undefined);
}
