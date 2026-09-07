/** The slice of Google Identity Services (https://accounts.google.com/gsi/client)
    Rosa uses: the OAuth 2.0 code client. A popup with Google's account chooser
    (`select_account`) hands back a one-time code; the Worker exchanges it for an
    ID token and verifies that. Chosen over the rendered GIS button, which turns
    into a personalised "Continue as <last account>" and skips the chooser.
    The script is injected lazily by account.ts, never bundled. */
interface GsiCodeResponse {
  code?: string;
  scope?: string;
  error?: string; // "access_denied" | "popup_closed" | "popup_failed_to_open" | ...
  error_description?: string;
}

interface GsiCodeClientConfig {
  client_id: string;
  scope: string;
  ux_mode?: "popup" | "redirect";
  select_account?: boolean;
  callback: (r: GsiCodeResponse) => void;
  error_callback?: (e: { type: string; message?: string }) => void;
}

interface GsiCodeClient {
  requestCode(): void;
}

interface GsiOauth2 {
  initCodeClient(config: GsiCodeClientConfig): GsiCodeClient;
}

interface Window {
  google?: { accounts?: { oauth2?: GsiOauth2 } };
}
