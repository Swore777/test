import type { ReactNode } from "react";
import TelegramInit from "./telegram-init";

export const metadata = { title: "Каталог" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <TelegramInit />
        {children}
      </body>
    </html>
  );
}
