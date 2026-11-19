import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { RejectionTable } from "@/components/RejectionTable";
import { api } from "@/lib/api";

export const metadata: Metadata = { title: "Rejections" };

export default function RejectionsPage(props: PageProps<"/rejections">) {
  return (
    <>
      <h1>Rejection log</h1>
      <p className="sub">Every claim the Editor rejected or sent back for a rewrite, newest first.</p>
      <Suspense fallback={<p className="muted">Loading rejections…</p>}>
        <Rejections {...props} />
      </Suspense>
    </>
  );
}

async function Rejections({ searchParams }: PageProps<"/rejections">) {
  const onlyRejected = (await searchParams).only === "rejected";
  const rows = await api.rejections({ limit: 300, include_rewrite: !onlyRejected });
  return (
    <>
      <p>
        {onlyRejected ? (
          <Link href="/rejections">Show rewrites too</Link>
        ) : (
          <Link href="/rejections?only=rejected">Only rejected</Link>
        )}
      </p>
      <RejectionTable rows={rows} />
    </>
  );
}
