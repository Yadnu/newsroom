import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: { default: "Newsroom Archive", template: "%s · Newsroom Archive" },
  description: "Every sentence of every briefing, traced to its sources.",
};

export default function ArchiveLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <header className="top">
        <Link href="/archive" className="brand">
          Newsroom <span>Archive</span>
        </Link>
        <nav>
          <Link href="/">Press</Link>
          <Link href="/archive">Briefings</Link>
          <Link href="/rejections">Rejections</Link>
        </nav>
      </header>
      <main>{children}</main>
    </>
  );
}
