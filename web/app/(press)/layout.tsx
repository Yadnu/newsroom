import { Providers } from "@/src/features/feed/Providers";

export default function PressLayout({ children }: { children: React.ReactNode }) {
  return (
    <Providers>
      <div data-press className="fixed inset-0 bg-set font-body text-white">{children}</div>
    </Providers>
  );
}
