import { useEffect, useState } from "preact/hooks";
import { gaSetPrefs } from "./ga";
import type { Mode } from "./lib/swim";

/** Surf / swim mode preference. Persisted exactly like units (units.ts): a
    localStorage key plus a window event, so every mounted screen re-renders on a
    change. Per device, like units - it does not ride on the account row. */

const KEY = "rosa.mode";
const EVENT = "rosa:mode";

export function getMode(): Mode {
  try {
    return localStorage.getItem(KEY) === "swim" ? "swim" : "surf";
  } catch {
    return "surf";
  }
}

export function setMode(mode: Mode): void {
  localStorage.setItem(KEY, mode);
  gaSetPrefs({ mode });
  dispatchEvent(new Event(EVENT));
}

export function useMode(): Mode {
  const [mode, set] = useState<Mode>(getMode);
  useEffect(() => {
    const onChange = () => set(getMode());
    addEventListener(EVENT, onChange);
    return () => removeEventListener(EVENT, onChange);
  }, []);
  return mode;
}
