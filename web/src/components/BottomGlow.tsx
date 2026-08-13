// The particle half of the bottom treatment (the gradient mesh is .app::before
// in styles.css): specks drifting up out of the glow and fading as they climb.
// Same field wtw uses, in Rosa's two tones.
//
// Decoration only, so it is cheap to skip: reduced motion or a hidden tab and it
// never starts / quietly stops.

import { useEffect, useRef } from "preact/hooks";
import { mountParticles, type ParticleHandle } from "./particles";
import type { Theme } from "../theme";

// Light spends white specks, which only register where the mesh has tinted the
// page - they are meant to read as light on the water, not as dots. Dark keys to
// the two mesh tones and screens them out of the near-black page.
const PALETTE: Record<Theme, string[]> = {
  light: ["255, 255, 255"],
  dark: ["125, 185, 240", "94, 205, 205"],
};

export function BottomGlow({ theme }: { theme: Theme }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const still = matchMedia("(prefers-reduced-motion: reduce)");
    let handle: ParticleHandle | null = null;

    const start = () => {
      if (handle || document.hidden || still.matches) return;
      try {
        handle = mountParticles(canvas, {
          palette: PALETTE[theme],
          density: 1.4,
          speed: 1,
          alpha: theme === "dark" ? 0.08 : 0.5,
        });
      } catch {
        handle = null; // no 2D context - the gradient alone carries the look
      }
    };
    const stop = () => {
      handle?.stop();
      handle = null;
    };
    const onVisibility = () => (document.hidden ? stop() : start());

    start();
    document.addEventListener("visibilitychange", onVisibility);
    still.addEventListener("change", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
      still.removeEventListener("change", onVisibility);
    };
  }, [theme]);

  return <canvas ref={ref} class="glow-particles" aria-hidden="true" />;
}
