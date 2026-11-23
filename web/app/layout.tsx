import type { Metadata } from "next";
import { Inter, Oswald } from "next/font/google";

import "./globals.css";

const oswald = Oswald({ subsets: ["latin"], variable: "--font-oswald", display: "swap" });
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Newsroom", template: "%s · Newsroom" },
  description: "Live news from the press desk, fact-checked on air.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${oswald.variable} ${inter.variable}`}>
      <body>{children}</body>
    </html>
  );
}
