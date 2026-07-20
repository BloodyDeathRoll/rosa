import { useEffect, useRef, useState } from "preact/hooks";

/** Street-map header for the featured spot: CARTO Voyager tiles (Google-Maps-style
    cream land + blue water) centered on the spot with a single pin. Static <img>
    mosaic (no maplibre) so the home page stays light. */

const TILE = 256;
const Z = 15;

const lonToX = (lon: number) => ((lon + 180) / 360) * TILE * 2 ** Z;
const latToY = (lat: number) => {
  const s = Math.sin((lat * Math.PI) / 180);
  return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * TILE * 2 ** Z;
};
const wrap = (n: number) => ((n % 2 ** Z) + 2 ** Z) % 2 ** Z;

export function SatMap({ lat, lon, height = 176 }: { lat: number; lon: number; height?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [w, setW] = useState(398);
  const H = height;
  useEffect(() => {
    const measure = () => ref.current && setW(ref.current.clientWidth);
    measure();
    addEventListener("resize", measure);
    return () => removeEventListener("resize", measure);
  }, []);

  const left = lonToX(lon) - w / 2;
  const top = latToY(lat) - H / 2;
  const tiles: { x: number; y: number; px: number; py: number }[] = [];
  for (let x = Math.floor(left / TILE); x <= Math.floor((left + w) / TILE); x++) {
    for (let y = Math.floor(top / TILE); y <= Math.floor((top + H) / TILE); y++) {
      tiles.push({ x, y, px: x * TILE - left, py: y * TILE - top });
    }
  }

  return (
    <span class="sat-map" ref={ref} style={`height:${H}px`}>
      <span class="sm-tiles">
        {tiles.map((t) => (
          <img
            key={`${t.x}-${t.y}`}
            src={`https://basemaps.cartocdn.com/rastertiles/voyager/${Z}/${wrap(t.x)}/${wrap(t.y)}@2x.png`}
            style={`left:${t.px}px;top:${t.py}px`}
            width={TILE}
            height={TILE}
            alt=""
            loading="lazy"
          />
        ))}
      </span>
      <svg class="sm-pin" width="30" height="30" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7z"
          fill="var(--accent)"
          stroke="#fff"
          stroke-width="1.5"
        />
        <circle cx="12" cy="9" r="2.4" fill="#fff" />
      </svg>
      <span class="sm-attr">© OpenStreetMap © CARTO</span>
    </span>
  );
}
