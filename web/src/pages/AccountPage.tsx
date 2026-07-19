import { AppHeader } from "../components/AppHeader";
import type { Theme } from "../theme";

export function AccountPage({
  theme,
  onToggleTheme,
}: {
  theme: Theme;
  onToggleTheme: () => void;
}) {
  return (
    <main class="page">
      <AppHeader theme={theme} onToggleTheme={onToggleTheme} />
      <h2 class="list-title">Account</h2>
      <div class="card plain">
        <p>
          Rosa doesn't need an account yet — favorites and settings live on this device.
        </p>
        <p class="muted-note">
          Accounts arrive with swell alerts and cross-device sync. The forecast stays free
          either way.
        </p>
      </div>
    </main>
  );
}
