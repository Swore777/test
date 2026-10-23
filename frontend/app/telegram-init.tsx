"use client";

import Script from "next/script";

// В обычном браузере скрипт просто ничего не делает; внутри Telegram сообщаем,
// что Mini App готов, и разворачиваем его на всю высоту.
export default function TelegramInit() {
  return (
    <Script
      src="https://telegram.org/js/telegram-web-app.js"
      strategy="afterInteractive"
      onLoad={() => {
        const tg = (window as any).Telegram?.WebApp;
        tg?.ready();
        tg?.expand();
      }}
    />
  );
}
