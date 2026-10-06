import { useState } from "preact/hooks";
import { fromForeignApp, sendForeignAppAnswer } from "../probe";

/** "Which app sent you here?" - shown ONLY on a load that arrived through the unknown
    Android app's link (probe.ts: `webview=ANDROID_WEBVIEW` or its token pair). Every
    other visitor never sees it. TEMPORARY, removed with the probe once the app is named.

    One line in the visitor's language (the probe rows are Arabic, Turkish, Persian,
    Spanish and English), a text box, Send, and an X. Same card as the consent bar. */
const TEXT: Record<string, { q: string; ph: string; send: string; thanks: string }> = {
  en: { q: "Which app brought you here?", ph: "App name", send: "Send", thanks: "Thank you!" },
  ar: { q: "ما هو التطبيق الذي أوصلك إلى هنا؟", ph: "اسم التطبيق", send: "إرسال", thanks: "شكراً لك!" },
  tr: { q: "Buraya hangi uygulamadan geldiniz?", ph: "Uygulama adı", send: "Gönder", thanks: "Teşekkürler!" },
  fa: { q: "از کدام برنامه به اینجا آمدید؟", ph: "نام برنامه", send: "ارسال", thanks: "متشکریم!" },
  es: { q: "¿Qué aplicación te trajo aquí?", ph: "Nombre de la app", send: "Enviar", thanks: "¡Gracias!" },
  fr: { q: "Quelle application vous a amené ici ?", ph: "Nom de l'app", send: "Envoyer", thanks: "Merci !" },
  ru: { q: "Какое приложение привело вас сюда?", ph: "Название приложения", send: "Отправить", thanks: "Спасибо!" },
};
const RTL = new Set(["ar", "fa"]);

export function ForeignAppAsk() {
  const [state, setState] = useState<"ask" | "sent" | "closed">("ask");
  const [value, setValue] = useState("");
  if (!fromForeignApp() || state === "closed") return null;

  const lang = navigator.language.slice(0, 2).toLowerCase();
  const t = TEXT[lang] ?? TEXT.en!;
  const dir = RTL.has(lang) ? "rtl" : "ltr";

  const send = () => {
    const a = value.trim();
    if (!a) return;
    sendForeignAppAnswer(a, navigator.language);
    setState("sent");
    setTimeout(() => setState("closed"), 1500);
  };

  return (
    <div class="consent-bar ask-app" dir={dir} role="dialog" aria-label={t.q}>
      {state === "sent" ? (
        <div class="consent-text">
          <b>{t.thanks}</b>
        </div>
      ) : (
        <>
          <div class="consent-text">
            <b>{t.q}</b>
            <input
              class="ask-app-input"
              type="text"
              maxLength={200}
              placeholder={t.ph}
              value={value}
              onInput={(e) => setValue((e.currentTarget as HTMLInputElement).value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
            />
          </div>
          <div class="consent-actions">
            <button class="consent-yes" onClick={send} disabled={!value.trim()}>
              {t.send}
            </button>
            <button class="consent-no ask-app-close" aria-label="Close" onClick={() => setState("closed")}>
              ×
            </button>
          </div>
        </>
      )}
    </div>
  );
}
