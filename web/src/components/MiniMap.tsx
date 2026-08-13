import { useEffect, useRef, useState } from "preact/hooks";

/** Surfline-style satellite header for the featured spot: ESRI World Imagery
    tiles centered on the spot with a single pin. Static <img> mosaic (no
    maplibre) so the home page stays light. */

const TILE = 256;
/* z15 framed roughly 1.2 km across, which is tighter than most breaks: a spot
   whose coordinate sits offshore (Ollie's Point, Witch's Rock) filled the whole
   card with featureless water or canopy and read as a broken image. z13 is
   ~4.9 km across, so the headland, the bay and the beach are all in frame and
   the card is recognisable as the place. Beach-front spots (Beit Yanai, Playa
   Yankee) read fine at either. */
const Z = 13;

const lonToX = (lon: number) => ((lon + 180) / 360) * TILE * 2 ** Z;
const latToY = (lat: number) => {
  const s = Math.sin((lat * Math.PI) / 180);
  return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * TILE * 2 ** Z;
};
const wrap = (n: number) => ((n % 2 ** Z) + 2 ** Z) % 2 ** Z;

export function SatMap({
  lat,
  lon,
  height = 176,
  pin = true,
}: {
  lat: number;
  lon: number;
  height?: number;
  pin?: boolean;
}) {
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
            src={`https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${Z}/${wrap(t.y)}/${wrap(t.x)}`}
            style={`left:${t.px}px;top:${t.py}px`}
            width={TILE}
            height={TILE}
            alt=""
            loading="lazy"
          />
        ))}
      </span>
      {pin && (
        <svg class="sm-pin" width="30" height="30" viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7z"
            fill="var(--accent)"
            stroke="#fff"
            stroke-width="1.5"
          />
          <circle cx="12" cy="9" r="2.4" fill="#fff" />
        </svg>
      )}
      <span class="sm-attr">Imagery © Esri</span>
    </span>
  );
}
