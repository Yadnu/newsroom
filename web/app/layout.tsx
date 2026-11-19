import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Newsroom Archive", template: "%s · Newsroom Archive" },
  description: "Every sentence of every briefing, traced to its sources.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <header className="top">
          <Link href="/" className="brand">
            Newsroom <span>Archive</span>
          </Link>
          <nav>
            <Link href="/">Briefings</Link>
            <Link href="/rejections">Rejections</Link>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
