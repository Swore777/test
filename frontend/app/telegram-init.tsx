"use client";

import { useRouter } from "next/navigation";
import Script from "next/script";
import { useEffect } from "react";

// В обычном браузере скрипт просто ничего не делает; внутри Telegram сообщаем,
// что Mini App готов, и разворачиваем его на всю высоту.
// Telegram держит свёрнутый Mini App в памяти и при повторном открытии показывает
// старую страницу без запроса к серверу, поэтому при возврате перезапрашиваем список.
export default function TelegramInit() {
  const router = useRouter();

  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") router.refresh();
    };
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, [router]);

  return (
    <Script
      src="https://telegram.org/js/telegram-web-app.js"
      strategy="afterInteractive"
      onLoad={() => {
        const tg = (window as any).Telegram?.WebApp;
        tg?.ready();
        tg?.expand();
        tg?.onEvent?.("activated", () => router.refresh());
      }}
    />
  );
}
