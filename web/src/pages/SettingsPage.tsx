import { AppHeader } from "../components/AppHeader";
import { setUnits, useUnits, type Units } from "../units";
import type { Theme } from "../theme";

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div class="setting">
      <span class="setting-label">{label}</span>
      <div class="segmented" role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button
            key={o.value}
            role="radio"
            aria-checked={value === o.value}
            onClick={() => onChange(o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function SettingsPage({
  theme,
  onToggleTheme,
}: {
  theme: Theme;
  onToggleTheme: () => void;
}) {
  const units = useUnits();
  const update = (patch: Partial<Units>) => setUnits({ ...units, ...patch });

  return (
    <main class="page">
      <AppHeader theme={theme} onToggleTheme={onToggleTheme} />
      <h2 class="list-title">Units</h2>
      <Segmented
        label="Temperature"
        value={units.temp}
        options={[
          { value: "c", label: "°C" },
          { value: "f", label: "°F" },
        ]}
        onChange={(temp) => update({ temp })}
      />
      <Segmented
        label="Height"
        value={units.height}
        options={[
          { value: "m", label: "meters" },
          { value: "ft", label: "feet" },
        ]}
        onChange={(height) => update({ height })}
      />
      <p class="muted-note settings-note">
        Settings live on this device. Accounts arrive with swell alerts and cross-device
        sync — the forecast stays free either way.
      </p>
    </main>
  );
}
