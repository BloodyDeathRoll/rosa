/** Micro-tidal placeholder curve exactly as mocked (M2 sine) — the pipeline
    doesn't publish tides yet; Med spots are sparkline-only by design. Shared
    by the spot screen and the Home extended card. */
export function TideSection({ nowT, metric }: { nowT: string; metric: boolean }) {
  const pts: string[] = [];
  for (let t = 0; t <= 48; t++) {
    const hr = t / 2;
    const y = 35 - 20 * Math.sin(((hr - 8.2) / 12.42) * 2 * Math.PI);
    pts.push(`${((hr / 24) * 326).toFixed(1)},${y.toFixed(1)}`);
  }
  const line = `M${pts.join(" L")}`;
  const nowX = (
    ((Number(nowT.slice(11, 13)) + Number(nowT.slice(14, 16)) / 60) / 24) *
    326
  ).toFixed(1);
  return (
    <div class="tide-sec">
      <div class="head">
        <span class="eyebrow">Tide</span>
        <span class="note">~0.3 m range — barely matters here</span>
      </div>
      <svg width="358" height="52" viewBox="0 0 326 70" preserveAspectRatio="none">
        <path d={`${line} L326,70 L0,70 Z`} fill="rgba(217,119,86,0.10)" stroke="none" />
        <path d={line} fill="none" stroke="var(--accent)" stroke-width="1.5" />
        <line
          x1={nowX}
          y1="6"
          x2={nowX}
          y2="64"
          stroke="var(--foreground)"
          stroke-width="1"
          stroke-dasharray="2 3"
        />
      </svg>
      <div class="lohi tabular">
        <span class="hi">High 14:20 · {metric ? "0.4 m" : "1.3 ft"}</span>
        <span class="lo">Low 21:05 · {metric ? "0.2 m" : "0.7 ft"}</span>
      </div>
    </div>
  );
}
