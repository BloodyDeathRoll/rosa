/** A one-line hello for visitors Tango Live sends here by mistake.

    Since 2026-09-11 a Tango promo card links to rosa.surf and opens it in Tango's
    in-app webview, with Tango's own `?token=…&accountId=…&username=…&webview=
    ANDROID_WEBVIEW` on the URL (docs/SESSIONS.md 2026-10-06). Those visitors expected
    something else. On exactly those loads, and never otherwise, this card says what
    Rosa is and that Tango sent them here by mistake, in their own language, with one
    OK. Nothing is sent or stored - the query is read once at boot and that is all. */
import { useState } from "preact/hooks";

const FROM_TANGO = (() => {
  const q = new URLSearchParams(location.search);
  return q.get("webview") === "ANDROID_WEBVIEW" || (q.has("token") && q.has("accountId"));
})();

/** Languages seen on these loads (GA4: Arabic first by far, then Turkish, Persian,
    Spanish, English, French, Russian) plus the other large Tango markets. */
const TEXT: Record<string, { hi: string; body: string; ok: string }> = {
  en: {
    hi: "Hi!",
    body: "This is a surf forecast app. You are welcome to look around, but Tango sent you here by mistake.",
    ok: "OK",
  },
  ar: {
    hi: "مرحباً!",
    body: "هذا تطبيق لتوقعات الأمواج. أهلاً بك هنا، لكن تطبيق Tango أرسلك إلى هنا عن طريق الخطأ.",
    ok: "حسناً",
  },
  tr: {
    hi: "Merhaba!",
    body: "Bu bir dalga tahmini uygulaması. Buyurun bakın, ama Tango sizi buraya yanlışlıkla gönderdi.",
    ok: "Tamam",
  },
  fa: {
    hi: "سلام!",
    body: "این یک برنامهٔ پیش‌بینی موج است. خوش آمدید، اما Tango شما را به اشتباه به اینجا فرستاده است.",
    ok: "باشه",
  },
  ur: {
    hi: "ہیلو!",
    body: "یہ لہروں کی پیش گوئی کی ایپ ہے۔ آپ کو خوش آمدید، لیکن Tango نے آپ کو غلطی سے یہاں بھیج دیا۔",
    ok: "ٹھیک ہے",
  },
  hi: {
    hi: "नमस्ते!",
    body: "यह एक लहर पूर्वानुमान ऐप है। आपका स्वागत है, लेकिन Tango ने आपको गलती से यहाँ भेज दिया।",
    ok: "ठीक है",
  },
  es: {
    hi: "¡Hola!",
    body: "Esta es una app de pronóstico de olas. Puedes quedarte a mirar, pero Tango te envió aquí por error.",
    ok: "Entendido",
  },
  pt: {
    hi: "Olá!",
    body: "Este é um app de previsão de ondas. Fique à vontade, mas o Tango enviou você para cá por engano.",
    ok: "OK",
  },
  fr: {
    hi: "Bonjour !",
    body: "Ceci est une application de prévisions de vagues. Vous êtes le bienvenu, mais Tango vous a envoyé ici par erreur.",
    ok: "OK",
  },
  it: {
    hi: "Ciao!",
    body: "Questa è un'app di previsioni delle onde. Sei il benvenuto, ma Tango ti ha mandato qui per errore.",
    ok: "OK",
  },
  de: {
    hi: "Hallo!",
    body: "Das ist eine Wellenvorhersage-App. Du bist willkommen, aber Tango hat dich aus Versehen hierher geschickt.",
    ok: "OK",
  },
  ru: {
    hi: "Привет!",
    body: "Это приложение с прогнозом волн. Добро пожаловать, но Tango отправил вас сюда по ошибке.",
    ok: "ОК",
  },
  id: {
    hi: "Halo!",
    body: "Ini aplikasi prakiraan ombak. Silakan melihat-lihat, tapi Tango mengirim Anda ke sini secara tidak sengaja.",
    ok: "OK",
  },
};
const RTL = new Set(["ar", "fa", "ur"]);

export function TangoNotice() {
  const [open, setOpen] = useState(FROM_TANGO);
  if (!open) return null;

  const lang = navigator.language.slice(0, 2).toLowerCase();
  const t = TEXT[lang] ?? TEXT.en!;
  const dir = RTL.has(lang) ? "rtl" : "ltr";

  return (
    <div class="consent-bar tango-notice" dir={dir} role="dialog" aria-labelledby="tango-title">
      <div class="consent-text">
        <b id="tango-title">{t.hi}</b>
        <small>{t.body}</small>
      </div>
      <div class="consent-actions">
        <button class="consent-yes" onClick={() => setOpen(false)}>
          {t.ok}
        </button>
      </div>
    </div>
  );
}
